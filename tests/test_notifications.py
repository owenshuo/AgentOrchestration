import pytest

from src.ui.notifications import render_task_toast, render_task_toast_text


ATTACK_PAYLOADS = [
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
]

ACTIVE_MARKUP = (
    "<script",
    "<svg",
    "<img",
    "<button",
)


@pytest.mark.parametrize(
    ("payload", "escaped"),
    ATTACK_PAYLOADS,
)
def test_task_toast_escapes_user_controlled_task_names(payload, escaped):
    html = render_task_toast(payload, "success")

    assert escaped in html
    assert payload not in html
    assert not _contains_active_markup(html)


@pytest.mark.parametrize(("payload", "escaped"), ATTACK_PAYLOADS)
@pytest.mark.parametrize("variant", ["success", "failure", "info", "warning"])
def test_task_toast_escapes_detail_payloads(variant, payload, escaped):
    html = render_task_toast("deploy", variant, detail=payload)

    assert escaped in html
    assert payload not in html
    assert not _contains_active_markup(html)


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
    payload = "<img onerror=alert(1)>"

    with pytest.raises(ValueError, match="unsupported toast variant") as error:
        render_task_toast("safe", payload)

    assert payload not in str(error.value)


def _contains_active_markup(html):
    lowered = html.lower()
    return any(marker in lowered for marker in ACTIVE_MARKUP)
