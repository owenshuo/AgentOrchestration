import pytest

from src.ui.notifications import render_task_toast, render_task_toast_text


@pytest.mark.parametrize(
    ("payload", "escaped"),
    [
        (
            "<img src=x onerror=alert(1)>",
            "&lt;img src=x onerror=alert(1)&gt;",
        ),
        (
            "<svg><script>alert(1)</script></svg>",
            "&lt;svg&gt;&lt;script&gt;alert(1)&lt;/script&gt;&lt;/svg&gt;",
        ),
        (
            '" autofocus onfocus=alert(1) x="',
            "&quot; autofocus onfocus=alert(1) x=&quot;",
        ),
    ],
)
def test_task_toast_escapes_user_controlled_task_names(payload, escaped):
    html = render_task_toast(payload, "success")

    assert escaped in html
    assert payload not in html
    assert "<script" not in html.lower()
    assert "<svg" not in html.lower()
    assert "<img" not in html.lower()
    assert "onerror=" not in html.lower().replace("onerror=alert", "")


def test_task_toast_escapes_failure_variant_and_detail():
    html = render_task_toast(
        "deploy <b>prod</b>",
        "failure",
        detail="<button onclick=steal()>retry</button>",
    )

    assert "deploy &lt;b&gt;prod&lt;/b&gt;" in html
    assert "&lt;button onclick=steal()&gt;retry&lt;/button&gt;" in html
    assert "<b>prod</b>" not in html
    assert "<button" not in html
    assert "failed" in html


def test_all_allowed_variants_use_fixed_formatting():
    assert 'toast--success"' in render_task_toast("task", "success")
    assert 'toast--failure"' in render_task_toast("task", "failure")
    assert 'toast--info"' in render_task_toast("task", "info")
    assert 'toast--warning"' in render_task_toast("task", "warning")


def test_text_rendering_never_adds_markup():
    text = render_task_toast_text(
        "<img src=x>",
        "warning",
        detail="<script>x</script>",
    )

    assert text == "Task <img src=x> needs attention. <script>x</script>"


def test_task_toast_rejects_unknown_variant_before_rendering():
    with pytest.raises(ValueError, match="unsupported toast variant"):
        render_task_toast("safe", "<img onerror=alert(1)>")
