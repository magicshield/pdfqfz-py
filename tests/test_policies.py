from pdfqfz.core import policies as P
from pdfqfz.model.spec import SeamType, StampType


# --- SeamStampPolicy.cs ---

def test_single_page_skip_all_but_none():
    for s in (SeamType.ALL, SeamType.ODD, SeamType.EVEN, SeamType.CUSTOM):
        assert P.should_skip_seam_single_page(1, s) is True
    assert P.should_skip_seam_single_page(1, SeamType.NONE) is False
    assert P.should_skip_seam_single_page(2, SeamType.ALL) is False


# --- StampRenderPolicy.cs ---

def test_render_visible_stamp():
    assert P.should_render_normal_stamp(StampType.NONE) is False
    for s in (StampType.NO_FIRST, StampType.NO_LAST, StampType.ALL, StampType.CUSTOM):
        assert P.should_render_normal_stamp(s) is True


# --- StampPlacementPolicy.cs ---

def test_placement():
    assert P.should_draw_normal_on_page(5, 0, 5, True) is False      # 签名页排除
    assert P.should_draw_normal_on_page(3, 0, 5, False) is True
    assert P.should_draw_normal_on_page(1, 1, 0, False) is False      # excluded 生效
    assert P.should_draw_normal_on_page(2, 1, 5, True) is True


# --- 页选择 ---

def test_seam_target_pages():
    assert P.seam_target_pages(1, SeamType.ALL) == []
    assert P.seam_target_pages(5, SeamType.ALL) == [1, 2, 3, 4, 5]
    assert P.seam_target_pages(5, SeamType.ODD) == [1, 3, 5]
    assert P.seam_target_pages(5, SeamType.EVEN) == [2, 4]
    assert P.seam_target_pages(7, SeamType.CUSTOM, [5, 1, 3, 3]) == [1, 3, 5]
    assert P.seam_target_pages(5, SeamType.NONE) == []


def test_normal_page_plan():
    assert P.normal_page_plan(5, StampType.NO_FIRST) == (1, 5, [2, 3, 4, 5])
    assert P.normal_page_plan(1, StampType.NO_FIRST) == (0, 1, [1])   # 单页例外不排除
    assert P.normal_page_plan(5, StampType.NO_LAST) == (5, 1, [1, 2, 3, 4])
    assert P.normal_page_plan(5, StampType.ALL) == (0, 5, [1, 2, 3, 4, 5])
    assert P.normal_page_plan(5, StampType.CUSTOM, [2, 4]) == (0, 4, [2, 4])
    assert P.normal_page_plan(5, StampType.CUSTOM, []) == (0, 1, [])  # sig 保持 C# 初值 1
    assert P.normal_page_plan(5, StampType.NONE) == (0, 5, [])


# --- 切条 ---

def test_strip_widths_sum_and_head_third():
    for W, n in [(300, 3), (97, 7), (1000, 30), (472, 2), (50, 1), (7, 5), (1, 3)]:
        ws = P.strip_widths(W, n)
        assert len(ws) == n
        assert sum(ws) == W
    assert P.strip_widths(300, 3) == [100, 66, 134]   # C#: w1=100, w=(200)//3=66, 末条吸收余数
    # w1=301//3=100, w=(301-100)//4=50, 条=[100,50,50], 末条=301-200=101
    assert P.strip_widths(301, 4) == [100, 50, 50, 101]


def test_strip_widths_matches_csharp_subimages():
    # C#: w1=W/3; w=(W-w1)/n; 条0=w1, 条1..n-2=w, 条n-1=余数
    W, n = 473, 6
    w1 = W // 3
    w = (W - w1) // n
    expect = [w1] + [w] * (n - 2) + [W - w1 - w * (n - 2)]
    assert P.strip_widths(W, n) == expect


# --- 分组(修正版 ceil) ---

def test_seam_groups():
    assert P.seam_groups(10, 20) == [10]
    assert P.seam_groups(20, 20) == [20]           # C# bug: 分成 2 组 10+10（多盖一遍）
    assert P.seam_groups(30, 20) == [15, 15]
    assert P.seam_groups(25, 20) == [13, 12]
    assert P.seam_groups(40, 20) == [20, 20]       # C# bug: 14+13+13
    assert P.seam_groups(21, 20) == [11, 10]
    assert P.seam_groups(100, 20) == [20, 20, 20, 20, 20]
    assert P.seam_groups(0, 20) == []
    assert sum(P.seam_groups(37, 5)) == 37
    assert len(P.seam_groups(37, 5)) == 8


# --- WhiteTransparencyHelper ---

def test_clamp_tolerance():
    assert P.clamp_tolerance(-1) == 0
    assert P.clamp_tolerance(20) == 20
    assert P.clamp_tolerance(99) == 50


# --- PreviewValueSanitizer ---

def test_sanitizers():
    assert P.keep_digits_only("12a3b") == "123"
    assert P.keep_digits_only("") == ""
    assert P.keep_signed_integer("--1a2-3") == "-123"
    assert P.keep_signed_integer("1-2") == "12"
    assert P.clamp_int("", 40, 0, 100) == 40
    assert P.clamp_int("-5", 40, 0, 100) == 0
    assert P.clamp_int("150", 40, 0, 100) == 100
    assert P.clamp_int("42", 40, 0, 100) == 42


# --- PreviewStampLayout ---

def test_overlay_size():
    assert P.overlay_size(40, 600, 300, 500, 1000) == (56, 28)
    for bad in [(0, 600, 300, 500, 1000), (40, 0, 300, 500, 1000),
                (40, 600, 0, 500, 1000), (40, 600, 300, 0, 1000),
                (40, 600, 300, 500, 0), (-1, -1, -1, -1, -1)]:
        assert P.overlay_size(*bad) == (72, 72)


# --- PreviewPanelLayout ---

def test_panel_layout():
    # 改进：只要要盖章就显示预览（C# 原版纯骑缝不显示）
    assert P.should_show_preview(StampType.NONE, SeamType.ALL) is True
    assert P.should_show_preview(StampType.NONE, SeamType.NONE) is False
    assert P.should_show_preview(StampType.ALL, SeamType.ALL) is True
    assert P.should_show_preview(StampType.NONE, SeamType.CUSTOM) is True
    assert P.collapsed_client_width(629, 8) == 621
    assert P.collapsed_client_width(3, 8) == 1


# --- 预览显隐 ---

def test_overlay_visible():
    assert P.overlay_visible_for_page(StampType.CUSTOM, SeamType.NONE, 1, 5, False) is False
    assert P.overlay_visible_for_page(StampType.CUSTOM, SeamType.NONE, 1, 5, True) is True
    assert P.overlay_visible_for_page(StampType.NO_FIRST, SeamType.NONE, 1, 5, False) is False
    assert P.overlay_visible_for_page(StampType.NO_FIRST, SeamType.NONE, 1, 1, False) is True
    assert P.overlay_visible_for_page(StampType.NO_LAST, SeamType.NONE, 5, 5, False) is False
    assert P.overlay_visible_for_page(StampType.ALL, SeamType.NONE, 3, 5, False) is True


# --- 点击定位 ---

def test_click_to_position():
    px, py = P.click_to_position((100, 100), (500, 700), (56, 28))
    assert px == round((100 - 28) / (500 - 56), 4)
    assert py == round((100 - 14) / (700 - 28), 4)
    assert P.click_to_position((0, 0), (500, 700), (56, 28)) == (0.0, 0.0)
    assert P.click_to_position((500, 700), (500, 700), (56, 28)) == (1.0, 1.0)


# --- 随机参数 ---

def test_jitter_position_open_interval():
    assert P.jitter_position(0.77, 2) == 0.79
    assert P.jitter_position(0.77, -2) == 0.75
    assert P.jitter_position(0.0, -2) == 0.0    # 结果须在开区间
    assert P.jitter_position(1.0, 2) == 1.0
    assert abs(P.jitter_position(0.79, 1) - 0.80) < 1e-9


def test_jitter_angle_signature_page_zero():
    assert P.jitter_angle(5, 5, True, 2) == 0
    assert P.jitter_angle(3, 5, True, 2) == 2
    assert P.jitter_angle(3, 5, False, 2) == 0


# --- 签名代表页 ---

def test_signature_rep_page():
    assert P.signature_rep_page(5, StampType.NO_FIRST) == 5
    assert P.signature_rep_page(5, StampType.NO_LAST) == 1
    assert P.signature_rep_page(5, StampType.ALL) == 5
    assert P.signature_rep_page(5, StampType.CUSTOM, [2, 4]) == 4


# --- CommandLineFileLoader ---

def test_cli_help_renders():
    # argparse 会对含 % 的 help 做格式化，防回归
    import pytest as _pt
    from pdfqfz.cli.main import build_parser
    with _pt.raises(SystemExit) as e:
        build_parser().parse_args(["stamp", "--help"])
    assert e.value.code == 0


def test_collect_existing_pdfs(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.PDF").write_bytes(b"%PDF-1.4")
    (tmp_path / "c.txt").write_text("x")
    res = P.collect_existing_pdfs(
        ["a.pdf", "c.txt", "missing.pdf", "b.PDF", "  ", "subdir"],
        base_dir=tmp_path)
    assert res == [tmp_path / "a.pdf", tmp_path / "b.PDF"]
