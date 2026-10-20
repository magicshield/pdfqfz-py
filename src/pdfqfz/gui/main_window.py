"""主窗口：左侧参数表单 + 右侧预览 + 批量执行。"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from pdfqfz.config import inistore, paths, stamplib
from pdfqfz.core import pipeline
from pdfqfz.core import policies as P
from pdfqfz.core.imageops import build_assets
from pdfqfz.gui.job_runner import StampWorker
from pdfqfz.gui.preview_panel import PreviewPanel
from pdfqfz.model.spec import (Blend, CertMode, Edge, Mode, RotCrop, SeamType,
                               StampSpec, StampType)

SEAM_ITEMS = [("加盖骑缝章", SeamType.ALL), ("不加骑缝章", SeamType.NONE),
              ("奇数页", SeamType.ODD), ("偶数页", SeamType.EVEN),
              ("随意骑缝章(点击选页)", SeamType.CUSTOM)]
STAMP_ITEMS = [("不加印章", StampType.NONE), ("首页不加", StampType.NO_FIRST),
               ("尾页不加", StampType.NO_LAST), ("所有页", StampType.ALL),
               ("自定义(点击定位)", StampType.CUSTOM)]
EDGE_ITEMS = [("上", Edge.TOP), ("下", Edge.BOTTOM), ("左", Edge.LEFT), ("右", Edge.RIGHT)]
BLEND_ITEMS = [("叠加(保留文字层)", Blend.OVERLAY), ("合并(光栅化压扁)", Blend.MERGE)]
CERT_ITEMS = [("不签名", CertMode.NONE), ("自动自签证书", CertMode.SELF_SIGNED),
              ("自定义 pfx", CertMode.CUSTOM_PFX)]
CROP_ITEMS = [("旋转切边", RotCrop.CROP), ("不切边", RotCrop.EXPAND)]
MODE_ITEMS = [("目录模式", Mode.DIRECTORY), ("文件模式", Mode.FILES)]


def _combo(items, row_layout, label):
    row_layout.addWidget(QLabel(label))
    c = QComboBox()
    for text, _v in items:
        c.addItem(text)
    row_layout.addWidget(c)
    return c


class MainWindow(QMainWindow):
    def __init__(self, preset_files: list[Path] | None = None):
        super().__init__()
        self.setWindowTitle("PDFQFZ 骑缝章工具")
        self.positions: dict[tuple[str, int], tuple[float, float]] = {}
        self.worker: StampWorker | None = None
        self.assets = None
        self._build_ui()
        self._load_config()
        if preset_files:
            self.mode_cb.setCurrentIndex(1)
            self.sources = [Path(f) for f in preset_files]
            self.path_label.setText(", ".join(f.name for f in self.sources))
            self._open_preview(self.sources[0])

    # ---------- UI ----------

    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        form_box = QVBoxLayout()
        form_w = QWidget()
        form_w.setLayout(form_box)
        form_w.setMaximumWidth(430)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_w)
        scroll.setMaximumWidth(450)
        root.addWidget(scroll)

        self._build_form(form_box)

        right = QVBoxLayout()
        self.preview = PreviewPanel()
        nav = QHBoxLayout()
        btn_prev = QPushButton("◀")
        btn_next = QPushButton("▶")
        btn_prev.clicked.connect(lambda: (self.preview.prev_page(), self._update_page_label()))
        btn_next.clicked.connect(lambda: (self.preview.next_page(), self._update_page_label()))
        self.page_label = QLabel("- / -")
        nav.addWidget(btn_prev)
        nav.addWidget(self.page_label)
        nav.addWidget(btn_next)
        right.addLayout(nav)
        right.addWidget(self.preview, 1)
        rw = QWidget()
        rw.setLayout(right)
        root.addWidget(rw, 1)

        self.setCentralWidget(central)
        self.setAcceptDrops(True)
        self.preview.page_changed = self._update_page_label

    # ---------- 拖拽 / ESC ----------

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        files = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                 if u.toLocalFile().lower().endswith(".pdf")]
        if not files:
            return
        self.mode_cb.setCurrentIndex(1)
        self.sources = files
        self.src_dir = None
        self.path_label.setText(", ".join(p.name for p in files[:3])
                                + ("…" if len(files) > 3 else ""))
        self._open_preview(files[0])
        event.acceptProposedAction()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape and self.worker and self.worker.isRunning():
            self._cancel()
            return
        super().keyPressEvent(event)

    def _build_form(self, fb: QVBoxLayout):
        # 印章图片
        r = QHBoxLayout()
        self.seal_cb = QComboBox()
        btn_import = QPushButton("导入印章…")
        btn_import.clicked.connect(self._import_seal)
        r.addWidget(QLabel("印章"))
        r.addWidget(self.seal_cb, 1)
        r.addWidget(btn_import)
        fb.addLayout(r)

        # 输入
        r = QHBoxLayout()
        self.mode_cb = _combo(MODE_ITEMS, r, "输入")
        self.mode_cb.setCurrentIndex(1)  # 默认文件模式(对齐 C#)
        btn_pick = QPushButton("选择…")
        btn_pick.clicked.connect(self._pick_input)
        self.path_label = QLabel("(未选择)")
        r.addWidget(btn_pick)
        fb.addLayout(r)
        fb.addWidget(self.path_label)

        # 输出
        r = QHBoxLayout()
        r.addWidget(QLabel("输出"))
        self.out_label = QLabel("(源目录+前后缀)")
        btn_out = QPushButton("选择目录…")
        btn_out.clicked.connect(self._pick_out)
        self.save_src_cb = QCheckBox("保存在源文件夹")
        r.addWidget(self.out_label, 1)
        r.addWidget(btn_out)
        r.addWidget(self.save_src_cb)
        fb.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(QLabel("命名"))
        self.fix_str_ed = QLineEdit("已盖章")
        self.fix_type_cb = QComboBox()
        self.fix_type_cb.addItems(["后缀", "前缀"])
        r.addWidget(self.fix_str_ed)
        r.addWidget(self.fix_type_cb)
        self.multipass_cb = QCheckBox("多章连盖")
        r.addWidget(self.multipass_cb)
        fb.addLayout(r)

        # 骑缝
        r = QHBoxLayout()
        self.seam_cb = _combo(SEAM_ITEMS, r, "骑缝章")
        self.edge_cb = _combo(EDGE_ITEMS, r, "位置边")
        self.edge_cb.setCurrentIndex(3)  # 默认右缘(对齐 C#)
        r.addWidget(QLabel("距边%"))
        self.wz_ed = self._int_edit("50", 0, 100)
        r.addWidget(self.wz_ed)
        fb.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(QLabel("每组最大分割"))
        self.maxfgs_ed = self._int_edit("20", 1, 500)
        r.addWidget(self.maxfgs_ed)
        fb.addLayout(r)

        # 普通章
        r = QHBoxLayout()
        self.stamp_cb = _combo(STAMP_ITEMS, r, "印章")
        self.jitter_cb = QCheckBox("随机参数")
        r.addWidget(self.jitter_cb)
        fb.addLayout(r)

        # 外观参数
        r = QHBoxLayout()
        r.addWidget(QLabel("宽mm"))
        self.size_ed = self._int_edit("40", 1, 100)
        r.addWidget(self.size_ed)
        r.addWidget(QLabel("旋转°"))
        self.rot_ed = self._signed_edit("0")
        r.addWidget(self.rot_ed)
        r.addWidget(QLabel("透明%"))
        self.opacity_ed = self._int_edit("60", 0, 100)
        r.addWidget(self.opacity_ed)
        fb.addLayout(r)
        r = QHBoxLayout()
        self.white_cb = QCheckBox("白底转透明")
        self.white_cb.setChecked(True)
        r.addWidget(self.white_cb)
        r.addWidget(QLabel("容差"))
        self.tol_ed = self._int_edit("20", 0, 50)
        r.addWidget(self.tol_ed)
        self.crop_cb = _combo(CROP_ITEMS, r, "旋转")
        fb.addLayout(r)

        # 混合/加密
        r = QHBoxLayout()
        self.blend_cb = _combo(BLEND_ITEMS, r, "模式")
        r.addWidget(QLabel("打开密码"))
        self.read_pw_ed = QLineEdit()
        self.read_pw_ed.setEchoMode(QLineEdit.Password)
        r.addWidget(self.read_pw_ed)
        fb.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(QLabel("输出加密密码"))
        self.enc_pw_ed = QLineEdit()
        self.enc_pw_ed.setEchoMode(QLineEdit.Password)
        r.addWidget(self.enc_pw_ed)
        fb.addLayout(r)

        # 签名
        r = QHBoxLayout()
        self.cert_cb = _combo(CERT_ITEMS, r, "签名")
        self.cn_ed = QLineEdit()
        self.cn_ed.setPlaceholderText("签名人")
        r.addWidget(self.cn_ed)
        fb.addLayout(r)
        r = QHBoxLayout()
        self.pfx_label = QLabel("(pfx: 未选择)")
        self.pfx_pw_ed = QLineEdit()
        self.pfx_pw_ed.setEchoMode(QLineEdit.Password)
        self.pfx_pw_ed.setPlaceholderText("证书密码")
        btn_pfx = QPushButton("证书…")
        btn_pfx.clicked.connect(self._pick_pfx)
        r.addWidget(self.pfx_label, 1)
        r.addWidget(self.pfx_pw_ed)
        r.addWidget(btn_pfx)
        fb.addLayout(r)

        # 执行
        r = QHBoxLayout()
        self.run_btn = QPushButton("盖 章")
        self.run_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        r.addWidget(self.run_btn)
        r.addWidget(self.cancel_btn)
        fb.addLayout(r)
        self.progress = QProgressBar()
        fb.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        fb.addWidget(self.log)

        for w in (self.seal_cb, self.seam_cb, self.edge_cb, self.stamp_cb,
                  self.size_ed, self.rot_ed, self.opacity_ed, self.white_cb,
                  self.tol_ed, self.crop_cb, self.wz_ed):
            self._connect_params(w)
        self.sources: list[Path] = []
        self.src_dir: Path | None = None
        self.out_dir: Path | None = None
        self.pfx_path: Path | None = None

    def _int_edit(self, text, lo, hi) -> QLineEdit:
        ed = QLineEdit(text)
        ed.editingFinished.connect(
            lambda e=ed, l=lo, h=hi: self._normalize(e, l, h, signed=False))
        return ed

    def _signed_edit(self, text) -> QLineEdit:
        ed = QLineEdit(text)
        ed.editingFinished.connect(lambda: self._normalize(ed, -360, 360, signed=True))
        return ed

    def _normalize(self, ed: QLineEdit, lo, hi, signed):
        raw = P.keep_signed_integer(ed.text()) if signed else P.keep_digits_only(ed.text())
        ed.setText(str(P.clamp_int(raw, lo if signed else max(lo, 0), lo, hi)))

    def _connect_params(self, widget):
        if isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._params_changed)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self._params_changed)
        else:
            widget.currentIndexChanged.connect(self._params_changed)

    # ---------- 配置 ----------

    def _load_config(self):
        ov = inistore.load_overrides(paths.config_path())
        try:
            if "stamp_image" in ov and Path(str(ov["stamp_image"])).exists():
                pass
            for key, cb, items in (("seam", self.seam_cb, SEAM_ITEMS),
                                   ("edge", self.edge_cb, EDGE_ITEMS),
                                   ("normal", self.stamp_cb, STAMP_ITEMS),
                                   ("blend", self.blend_cb, BLEND_ITEMS),
                                   ("cert_mode", self.cert_cb, CERT_ITEMS),
                                   ("crop", self.crop_cb, CROP_ITEMS),
                                   ("mode", self.mode_cb, MODE_ITEMS)):
                if key in ov:
                    idx = [i for i, (_t, v) in enumerate(items) if v == ov[key]]
                    if idx:
                        cb.setCurrentIndex(idx[0])
            for key, ed in (("size_mm", self.size_ed), ("rotation", self.rot_ed),
                            ("opacity", self.opacity_ed), ("wz", self.wz_ed),
                            ("tolerance", self.tol_ed), ("max_strips", self.maxfgs_ed)):
                if key in ov:
                    ed.setText(str(ov[key]))
            if "fix_str" in ov:
                self.fix_str_ed.setText(ov["fix_str"])
            if "fix_type" in ov:
                self.fix_type_cb.setCurrentIndex(ov["fix_type"])
            self.white_cb.setChecked(bool(ov.get("white_to_alpha", True)))
            self.jitter_cb.setChecked(bool(ov.get("random_jitter", False)))
            self.multipass_cb.setChecked(bool(ov.get("multi_pass", False)))
            self.save_src_cb.setChecked(bool(ov.get("save_in_source", False)))
        except Exception:  # noqa: BLE001
            pass
        for img in stamplib.load(paths.stamplib_path()):
            if img.exists():
                self.seal_cb.addItem(str(img))
        if self.seal_cb.count():
            self.seal_cb.setCurrentIndex(0)

    # ---------- 选择 ----------

    def _import_seal(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择印章图片", "",
                                           "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if f:
            stamplib.append(paths.stamplib_path(), Path(f))
            self.seal_cb.clear()
            for img in stamplib.load(paths.stamplib_path()):
                if img.exists():
                    self.seal_cb.addItem(str(img))
            self.seal_cb.setCurrentText(f)
            self._params_changed()

    def _pick_input(self):
        if self.mode_cb.currentIndex() == 0:
            d = QFileDialog.getExistingDirectory(self, "选择 PDF 目录")
            if d:
                self.src_dir = Path(d)
                self.sources = []
                self.path_label.setText(d)
                pdfs = sorted(self.src_dir.rglob("*.pdf"))
                if pdfs:
                    self._open_preview(pdfs[0])
        else:
            fs, _ = QFileDialog.getOpenFileNames(self, "选择 PDF", "", "PDF (*.pdf)")
            if fs:
                self.sources = [Path(f) for f in fs]
                self.src_dir = None
                self.path_label.setText(", ".join(p.name for p in self.sources[:3])
                                        + ("…" if len(self.sources) > 3 else ""))
                self._open_preview(self.sources[0])

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.out_dir = Path(d)
            self.out_label.setText(d)

    def _pick_pfx(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择 pfx 证书", "", "PFX (*.pfx *.p12)")
        if f:
            self.pfx_path = Path(f)
            self.pfx_label.setText(Path(f).name)

    def _open_preview(self, path: Path):
        try:
            doc = pymupdf.open(str(path))
            if doc.needs_pass and not doc.authenticate(self.read_pw_ed.text()):
                doc.close()
                self.preview.set_document(None, None, 0)
                self.page_label.setText("需要密码")
                return
            n = doc.page_count
            doc.close()
        except Exception as e:  # noqa: BLE001
            self.page_label.setText(f"打开失败: {e}")
            return
        self.preview.set_document(path, self.read_pw_ed.text() or None, n)
        self._update_page_label()

    def _update_page_label(self):
        if self.preview.page_count:
            self.page_label.setText(f"{self.preview.page_index + 1} / {self.preview.page_count}")
        else:
            self.page_label.setText("- / -")

    # ---------- 参数 ----------

    def current_spec(self) -> StampSpec:
        seal = self.seal_cb.currentText()
        mode = MODE_ITEMS[self.mode_cb.currentIndex()][1]
        return StampSpec(
            mode=mode,
            sources=tuple(self.sources),
            src_dir=self.src_dir,
            out_dir=self.out_dir,
            stamp_image=Path(seal) if seal else None,
            size_mm=P.clamp_int(self.size_ed.text(), 40, 1, 100),
            rotation=P.clamp_int(P.keep_signed_integer(self.rot_ed.text()), 0, -360, 360),
            opacity=P.clamp_int(self.opacity_ed.text(), 60, 0, 100),
            tolerance=P.clamp_int(self.tol_ed.text(), 20, 0, 50),
            white_to_alpha=self.white_cb.isChecked(),
            crop=CROP_ITEMS[self.crop_cb.currentIndex()][1],
            seam=SEAM_ITEMS[self.seam_cb.currentIndex()][1],
            edge=EDGE_ITEMS[self.edge_cb.currentIndex()][1],
            wz=P.clamp_int(self.wz_ed.text(), 50, 0, 100),
            max_strips=P.clamp_int(self.maxfgs_ed.text(), 20, 1, 500),
            normal=STAMP_ITEMS[self.stamp_cb.currentIndex()][1],
            random_jitter=self.jitter_cb.isChecked(),
            save_in_source=self.save_src_cb.isChecked(),
            fix_type=self.fix_type_cb.currentIndex(),
            fix_str=self.fix_str_ed.text() or "已盖章",
            multi_pass=self.multipass_cb.isChecked(),
            blend=BLEND_ITEMS[self.blend_cb.currentIndex()][1],
            pdf_password=self.read_pw_ed.text() or None,
            encrypt_password=self.enc_pw_ed.text() or None,
            cert_mode=CERT_ITEMS[self.cert_cb.currentIndex()][1],
            signer_name=self.cn_ed.text(),
            pfx_path=self.pfx_path,
            pfx_password=self.pfx_pw_ed.text() or None,
            positions=self.positions,
        )

    def _params_changed(self):
        spec = self.current_spec()
        if spec.stamp_image and spec.stamp_image.exists():
            try:
                self.assets = build_assets(spec)
            except Exception:  # noqa: BLE001
                self.assets = None
        else:
            self.assets = None
        self.preview.set_params(spec, self.assets, self.positions)
        self.preview.setVisible(P.should_show_preview(spec.normal, spec.seam))

    # ---------- 执行 ----------

    def _start(self):
        spec = self.current_spec()
        if not spec.stamp_image or not spec.stamp_image.exists():
            QMessageBox.warning(self, "提示", "请先导入印章图片")
            return
        files = pipeline.scanner.collect_sources(spec)
        if not files:
            QMessageBox.warning(self, "提示", "请先选择要盖章的 PDF")
            return
        if spec.cert_mode != CertMode.NONE and spec.encrypt_password:
            QMessageBox.warning(self, "提示", "数字签名与加密输出不能同时使用")
            return
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.worker = StampWorker(spec)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _cancel(self):
        if self.worker:
            self.worker.cancel()
            self.log.appendPlainText("正在取消…")

    def _on_progress(self, i: int, total: int, text: str):
        self.progress.setValue(i)
        self.log.appendPlainText(f"[{i}/{total}] {text}")

    def _on_done(self, results: list):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        ok = sum(1 for r in results if r.ok)
        self.log.appendPlainText(f"完成：成功 {ok}/{len(results)}")
        if ok:
            spec = self.current_spec()
            try:
                inistore.save_spec(spec, paths.config_path())
            except Exception:  # noqa: BLE001
                pass
        self._update_page_label()
