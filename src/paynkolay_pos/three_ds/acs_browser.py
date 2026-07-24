"""Playwright-backed ACS browser automation for 3D Secure test flows."""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from playwright.async_api import Browser, BrowserContext, Frame, Locator, Page, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field, SecretStr

from paynkolay_pos.config import CardBrand
from paynkolay_pos.three_ds.acs_action import run_acs_otp_action
from paynkolay_pos.three_ds.acs_profile import (
    AcsBankProfile,
    AcsFieldEvidence,
    AcsFrameEvidence,
    AcsProfile,
    AcsProfileEvidence,
    detect_acs_profile,
)
from paynkolay_pos.three_ds.form_renderer import render_three_ds_form
from paynkolay_pos.three_ds.otp_resolver import resolve_otp_source

OTP_SELECTORS = (
    'input[name="otp"]',
    'input[name="OTP"]',
    'input[name*="otp" i]',
    'input[id*="otp" i]',
    'input[name*="sifre" i]',
    'input[id*="sifre" i]',
    'input[name*="password" i]',
    'input[id*="password" i]',
    'input[name*="pass" i]',
    'input[id*="pass" i]',
    'input[type="password"]',
    'input[type="tel"]',
    'input[type="text"]',
    'input[type="number"]',
)
SUBMIT_SELECTORS = (
    'button:has-text("Onay")',
    'button:has-text("Devam")',
    'button:has-text("Tamam")',
    'button:has-text("Gönder")',
    'button:has-text("Continue")',
    'button:has-text("Submit")',
    'input[type="submit"][value*="Onay" i]',
    'input[type="submit"][value*="Devam" i]',
    'input[type="submit"][value*="Tamam" i]',
    'input[type="submit"][value*="Gönder" i]',
    'input[type="submit"][value*="Continue" i]',
    'input[type="submit"][value*="Submit" i]',
    'input[type="button"][value*="Onay" i]',
    'input[type="button"][value*="Devam" i]',
    'input[type="button"][value*="Tamam" i]',
    'input[type="button"][value*="Gönder" i]',
    'input[type="button"][value*="Continue" i]',
    'input[type="button"][value*="Submit" i]',
    'button[type="submit"]',
    'input[type="submit"]',
    "button",
)
GARANTI_SMS_METHOD_SELECTORS = (
    'label:has-text("SMS")',
    'button:has-text("SMS")',
    'input[value*="SMS" i]',
    'input[id*="sms" i]',
    'input[name*="sms" i]',
)
GARANTI_CONTINUE_SELECTORS = (
    'button:has-text("Devam")',
    'button:has-text("Continue")',
    'input[type="submit"][value*="Devam" i]',
    'input[type="submit"][value*="Continue" i]',
    'button[type="submit"]',
    'input[type="submit"]',
)
ACS_FINAL_RETURN_SELECTORS = (
    'button:has-text("Üye işyerine dön")',
    'a:has-text("Üye işyerine dön")',
    '[role="button"]:has-text("Üye işyerine dön")',
    'button:has-text("Uye isyerine don")',
    'a:has-text("Uye isyerine don")',
    '[role="button"]:has-text("Uye isyerine don")',
    'button:has-text("İşyerine dön")',
    'a:has-text("İşyerine dön")',
    '[role="button"]:has-text("İşyerine dön")',
    'button:has-text("Isyerine don")',
    'a:has-text("Isyerine don")',
    '[role="button"]:has-text("Isyerine don")',
    'button:has-text("Merchant")',
    'a:has-text("Merchant")',
    '[role="button"]:has-text("Merchant")',
    'button:has-text("Devam")',
    'a:has-text("Devam")',
    '[role="button"]:has-text("Devam")',
    'button:has-text("Continue")',
    'a:has-text("Continue")',
    '[role="button"]:has-text("Continue")',
    'button:has-text("Tamam")',
    'a:has-text("Tamam")',
    '[role="button"]:has-text("Tamam")',
    'input[type="submit"][value*="Üye işyerine dön" i]',
    'input[type="submit"][value*="Uye isyerine don" i]',
    'input[type="submit"][value*="İşyerine dön" i]',
    'input[type="submit"][value*="Isyerine don" i]',
    'input[type="submit"][value*="Merchant" i]',
    'input[type="submit"][value*="Devam" i]',
    'input[type="submit"][value*="Continue" i]',
    'input[type="submit"][value*="Tamam" i]',
)
DEFAULT_FORM_BASE_URL = "https://vpostest.qnb.com.tr/PayforACSSimulator/"
INITIAL_CONTENT_TIMEOUT_MS = 60_000
_SENSITIVE_FRAME_LINE = re.compile(
    r"(?im)^(\s*(?:hashdata(?:v2)?|sx|signature|token|cvv|cvc|pan|card[_ ]?number|"
    r"otp|password)\b)[:=]?\s*.*$"
)
_SIX_DIGIT_VALUE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_LONG_CARD_VALUE = re.compile(r"(?<!\d)\d{12,19}(?!\d)")


class AcsBrowserAutomationResult(BaseModel):
    """Sanitized result returned by ACS browser automation."""

    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "use_enum_values": False,
    }

    completed: bool
    submitted: bool = False
    returned_to_callback: bool = False
    reason: str = Field(min_length=1, max_length=500)
    final_url: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=160)
    bank_profile: str | None = Field(default=None, max_length=80)
    screen_classification: str | None = Field(default=None, max_length=80)
    otp_strategy: str | None = Field(default=None, max_length=80)
    otp_input_found: bool = False
    submit_control_found: bool = False
    otp_selector: str | None = Field(default=None, max_length=120)
    submit_selector: str | None = Field(default=None, max_length=120)
    otp_resolution: dict[str, object] | None = None
    frames: tuple[AcsFrameEvidence, ...] = ()

    def summary(self) -> dict[str, object]:
        """Return a compact sanitized summary for API/session state."""

        resolution = self.otp_resolution or {}
        return {
            "status": "completed" if self.completed else "failed",
            "submitted": self.submitted,
            "classification": self.screen_classification,
            "reason": self.reason,
            "otp_source_type": resolution.get("source_type"),
            "otp_present": bool(resolution.get("otp_present")),
            "should_auto_submit": bool(resolution.get("should_auto_submit")),
            "final_url": self.final_url,
        }


class SelectorTarget:
    """Located visible element and owning frame."""

    def __init__(self, *, frame: Frame, selector: str, locator: Locator) -> None:
        self.frame = frame
        self.selector = selector
        self.locator = locator


async def complete_acs_browser_challenge(
    *,
    html: str,
    brand: CardBrand,
    configured_otp: SecretStr | None,
    callback_url: str,
    form_base_url: str = DEFAULT_FORM_BASE_URL,
    headed: bool = False,
    close_delay_seconds: float = 0.0,
    browser: Browser | None = None,
) -> AcsBrowserAutomationResult:
    """Complete a 3DS ACS challenge when a safe OTP source can be resolved."""

    document = render_three_ds_form(html)
    playwright = None
    owns_browser = browser is None
    context: BrowserContext | None = None
    try:
        if browser is None:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=not headed)
        context = await _new_browser_context(browser=browser, headed=headed)
        try:
            page = await context.new_page()
            await _set_initial_content(page, document.html, form_base_url=form_base_url)
            if not _has_auto_submit(document.html):
                await _submit_gateway_form_if_present(page)
            await _wait_for_network_quiet(page)

            if _same_origin_path(page.url, callback_url):
                evidence = await _profile_evidence_for_page(page, brand=brand)
                profile = detect_acs_profile(evidence)
                return _result(
                    completed=True,
                    submitted=False,
                    returned_to_callback=True,
                    reason="returned_to_callback_without_otp",
                    evidence=evidence,
                    profile=profile,
                )

            evidence = await _profile_evidence_for_page(page, brand=brand)
            profile = detect_acs_profile(evidence)
            otp_target = await _visible_selector_in_page_or_frames(page, OTP_SELECTORS)
            if otp_target is None:
                advanced_page = await _advance_garanti_sms_method_if_present(
                    context=context,
                    page=page,
                    profile=profile,
                )
                if advanced_page is not None:
                    page = advanced_page
                    evidence = await _profile_evidence_for_page(page, brand=brand)
                    profile = detect_acs_profile(evidence)
                    otp_target = await _visible_selector_in_page_or_frames(page, OTP_SELECTORS)
            if otp_target is None:
                return _result(
                    completed=False,
                    submitted=False,
                    reason=(
                        "acs_browser_client_rejected"
                        if _looks_like_browser_client_rejection(evidence)
                        else "otp_selector_not_found"
                    ),
                    evidence=evidence,
                    profile=profile,
                )

            submit_target = await _visible_selector_in_frame(otp_target.frame, SUBMIT_SELECTORS)
            if submit_target is None:
                return _result(
                    completed=False,
                    submitted=False,
                    reason="submit_selector_not_found",
                    evidence=evidence,
                    profile=profile,
                    otp_selector=otp_target.selector,
                )

            resolution = resolve_otp_source(
                profile=profile,
                evidence=evidence,
                configured_otp=configured_otp,
            )
            otp_submit_url = page.url
            await _prepare_otp_target_for_input(page=page, otp_target=otp_target)
            action = await run_acs_otp_action(
                otp_locator=otp_target.locator,
                submit_locator=submit_target.locator,
                resolution=resolution,
            )
            if not action.submitted:
                return _result(
                    completed=False,
                    submitted=False,
                    reason=action.reason,
                    evidence=evidence,
                    profile=profile,
                    otp_selector=otp_target.selector,
                    submit_selector=submit_target.selector,
                    otp_resolution=action.otp_resolution,
                )

            page = await _active_page(context=context, preferred_page=page)
            await _wait_for_network_quiet(page)
            page = await _force_submit_otp_form_if_still_present(
                context=context,
                page=page,
                otp_target=otp_target,
                submit_target=submit_target,
                before_submit_url=otp_submit_url,
            )
            page, returned_to_callback = await _follow_acs_final_return_if_present(
                context=context,
                page=page,
                callback_url=callback_url,
            )
            final_evidence = await _profile_evidence_for_page(page, brand=brand)
            if headed and close_delay_seconds > 0:
                await asyncio.sleep(close_delay_seconds)
            return _result(
                completed=True,
                submitted=True,
                returned_to_callback=returned_to_callback,
                reason=(
                    "otp_submitted"
                    if returned_to_callback
                    else "otp_submitted_callback_not_reached"
                ),
                evidence=final_evidence,
                profile=profile,
                otp_selector=otp_target.selector,
                submit_selector=submit_target.selector,
                otp_resolution=action.otp_resolution,
            )
        finally:
            await context.close()
    except PlaywrightError as exc:
        return AcsBrowserAutomationResult(
            completed=False,
            submitted=False,
            reason=f"playwright_error: {exc}"[:500],
            final_url=None,
            title=None,
            otp_resolution=None,
            frames=(),
        )
    except (TypeError, ValueError) as exc:
        return AcsBrowserAutomationResult(
            completed=False,
            submitted=False,
            reason=f"framework_error: {exc}"[:500],
            frames=(),
        )
    finally:
        if owns_browser and browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()


def _result(
    *,
    completed: bool,
    submitted: bool,
    reason: str,
    evidence: AcsProfileEvidence,
    profile: AcsProfile,
    returned_to_callback: bool = False,
    otp_selector: str | None = None,
    submit_selector: str | None = None,
    otp_resolution: dict[str, object] | None = None,
) -> AcsBrowserAutomationResult:
    return AcsBrowserAutomationResult(
        completed=completed,
        submitted=submitted,
        returned_to_callback=returned_to_callback,
        reason=reason,
        final_url=evidence.final_url,
        title=evidence.title,
        bank_profile=profile.bank_profile.value,
        screen_classification=profile.screen_classification.value,
        otp_strategy=profile.otp_strategy.value,
        otp_input_found=profile.otp_input_found,
        submit_control_found=profile.submit_control_found,
        otp_selector=otp_selector,
        submit_selector=submit_selector,
        otp_resolution=otp_resolution,
        frames=tuple(_sanitized_frame_evidence(frame) for frame in evidence.frames),
    )


async def _new_browser_context(*, browser: Browser, headed: bool) -> BrowserContext:
    if headed:
        return await browser.new_context(ignore_https_errors=True)
    return await browser.new_context(
        ignore_https_errors=True,
        user_agent=_chromium_user_agent(browser.version),
    )


async def _set_initial_content(page: Page, html: str, *, form_base_url: str) -> None:
    await page.set_content(
        _html_with_base_url(html, form_base_url=form_base_url),
        wait_until="domcontentloaded",
        timeout=INITIAL_CONTENT_TIMEOUT_MS,
    )


def _chromium_user_agent(version: str) -> str:
    normalized_version = version.strip()
    if re.fullmatch(r"\d+(?:\.\d+){0,3}", normalized_version) is None:
        normalized_version = "120.0.0.0"
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{normalized_version} Safari/537.36"
    )


def _looks_like_browser_client_rejection(evidence: AcsProfileEvidence) -> bool:
    title = (evidence.title or "").strip().lower()
    text = " ".join(frame.text_prefix.lower() for frame in evidence.frames)
    return title == "_404" or "404-qpg97-status" in text


def _sanitized_frame_evidence(frame: AcsFrameEvidence) -> AcsFrameEvidence:
    return frame.model_copy(update={"text_prefix": _sanitize_frame_text(frame.text_prefix)})


def _sanitize_frame_text(text: str) -> str:
    sanitized = _SENSITIVE_FRAME_LINE.sub(r"\1 <redacted>", text)
    sanitized = _SIX_DIGIT_VALUE.sub("<redacted>", sanitized)
    return _LONG_CARD_VALUE.sub("<redacted>", sanitized)


async def _submit_gateway_form_if_present(page: Page) -> None:
    form_count = await page.locator("form").count()
    if form_count == 0:
        return
    await page.locator("form").first.evaluate("form => form.submit()")


async def _advance_garanti_sms_method_if_present(
    *,
    context: BrowserContext,
    page: Page,
    profile: AcsProfile,
) -> Page | None:
    if profile.bank_profile is not AcsBankProfile.GARANTI:
        return None

    sms_target = await _visible_selector_in_page_or_frames(page, GARANTI_SMS_METHOD_SELECTORS)
    if sms_target is not None:
        try:
            await sms_target.locator.click()
        except PlaywrightError:
            return None

    continue_target = await _visible_selector_in_page_or_frames(page, GARANTI_CONTINUE_SELECTORS)
    if continue_target is None:
        return page

    return await _click_and_follow_page(
        context=context,
        page=page,
        locator=continue_target.locator,
    )


async def _follow_acs_final_return_if_present(
    *,
    context: BrowserContext,
    page: Page,
    callback_url: str,
) -> tuple[Page, bool]:
    page = await _active_page(context=context, preferred_page=page)
    if await _any_page_reached_callback(context=context, callback_url=callback_url):
        return page, True

    attempted_form_urls: set[str] = set()
    for _ in range(3):
        page = await _active_page(context=context, preferred_page=page)
        if await _submit_callback_form_if_present(
            page=page,
            callback_url=callback_url,
            attempted_form_urls=attempted_form_urls,
        ):
            page = await _active_page(context=context, preferred_page=page)
            await _wait_for_network_quiet(page)
            if await _any_page_reached_callback(context=context, callback_url=callback_url):
                return page, True
            continue

        final_return_target = await _visible_selector_in_page_or_frames(
            page,
            ACS_FINAL_RETURN_SELECTORS,
        )
        if final_return_target is None:
            break

        page = await _click_and_follow_page(
            context=context,
            page=page,
            locator=final_return_target.locator,
        )
        if await _any_page_reached_callback(context=context, callback_url=callback_url):
            return page, True

    page = await _active_page(context=context, preferred_page=page)
    return page, await _any_page_reached_callback(context=context, callback_url=callback_url)


async def _prepare_otp_target_for_input(*, page: Page, otp_target: SelectorTarget) -> None:
    with suppress(PlaywrightError):
        await page.bring_to_front()
    with suppress(PlaywrightError):
        await otp_target.locator.scroll_into_view_if_needed(timeout=2_000)


async def _force_submit_otp_form_if_still_present(
    *,
    context: BrowserContext,
    page: Page,
    otp_target: SelectorTarget,
    submit_target: SelectorTarget,
    before_submit_url: str,
) -> Page:
    page = await _active_page(context=context, preferred_page=page)
    if page.url != before_submit_url:
        return page
    if not await _selector_still_visible(otp_target):
        return page

    try:
        await otp_target.locator.press("Enter")
        await _wait_for_network_quiet(page)
    except PlaywrightError:
        pass
    page = await _active_page(context=context, preferred_page=page)
    if page.url != before_submit_url or not await _selector_still_visible(otp_target):
        return page

    try:
        submitted = await submit_target.locator.evaluate(
            """
            element => {
              const form = element.closest("form");
              if (!form) {
                return false;
              }
              try {
                if (typeof form.requestSubmit === "function") {
                  form.requestSubmit(element);
                } else {
                  form.submit();
                }
              } catch {
                form.submit();
              }
              return true;
            }
            """
        )
    except PlaywrightError:
        submitted = False
    if submitted:
        await _wait_for_network_quiet(page)
    return await _active_page(context=context, preferred_page=page)


async def _selector_still_visible(target: SelectorTarget) -> bool:
    try:
        return await target.locator.count() > 0 and await target.locator.is_visible(timeout=500)
    except PlaywrightError:
        return False


async def _submit_callback_form_if_present(
    *,
    page: Page,
    callback_url: str,
    attempted_form_urls: set[str],
) -> bool:
    callback_parts = urlsplit(callback_url)
    for frame in page.frames:
        forms = frame.locator("form")
        try:
            count = min(await forms.count(), 10)
        except PlaywrightError:
            continue
        for index in range(count):
            form = forms.nth(index)
            try:
                action = await form.get_attribute("action")
                method = (await form.get_attribute("method") or "get").lower()
            except PlaywrightError:
                continue
            absolute_action = urljoin(frame.url, action or "")
            safe_action = _safe_url(absolute_action)
            form_key = f"{frame.url}|{safe_action}|{index}"
            if (
                safe_action is None
                or form_key in attempted_form_urls
                or method not in {"get", "post"}
                or not _is_callback_or_merchant_return_url(safe_action, callback_parts)
            ):
                continue
            attempted_form_urls.add(form_key)
            try:
                await form.evaluate("form => form.submit()")
                return True
            except PlaywrightError:
                continue
    return False


def _is_callback_or_merchant_return_url(url: str, callback_parts: SplitResult) -> bool:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return False
    if (
        parts.scheme == callback_parts.scheme
        and parts.netloc == callback_parts.netloc
        and parts.path.rstrip("/") == callback_parts.path.rstrip("/")
    ):
        return True
    host = parts.netloc.lower()
    path = parts.path.lower()
    return "paynkolay" in host and any(
        marker in path for marker in ("callback", "three", "3d", "payment")
    )


async def _any_page_reached_callback(*, context: BrowserContext, callback_url: str) -> bool:
    for candidate in context.pages:
        if candidate.is_closed():
            continue
        try:
            if _same_origin_path(candidate.url, callback_url):
                await candidate.bring_to_front()
                return True
        except PlaywrightError:
            continue
    return False


async def _active_page(*, context: BrowserContext, preferred_page: Page) -> Page:
    if not preferred_page.is_closed():
        return preferred_page
    for candidate in reversed(context.pages):
        if not candidate.is_closed():
            await candidate.bring_to_front()
            return candidate
    return preferred_page


async def _click_and_follow_page(
    *,
    context: BrowserContext,
    page: Page,
    locator: Locator,
) -> Page:
    try:
        async with context.expect_page(timeout=3_000) as page_info:
            await locator.click()
        opened_page = await page_info.value
        await opened_page.bring_to_front()
        await _wait_for_network_quiet(opened_page)
        return opened_page
    except PlaywrightTimeoutError:
        await _wait_for_network_quiet(page)
        return page


async def _wait_for_network_quiet(page: Page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except PlaywrightTimeoutError:
            return


async def _visible_selector_in_page_or_frames(
    page: Page,
    selectors: tuple[str, ...],
) -> SelectorTarget | None:
    for frame in page.frames:
        target = await _visible_selector_in_frame(frame, selectors)
        if target is not None:
            return target
    return None


async def _visible_selector_in_frame(
    frame: Frame,
    selectors: tuple[str, ...],
) -> SelectorTarget | None:
    for selector in selectors:
        locator = frame.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible(timeout=1_000):
                return SelectorTarget(frame=frame, selector=selector, locator=locator)
        except PlaywrightError:
            continue
    return None


async def _profile_evidence_for_page(page: Page, *, brand: CardBrand) -> AcsProfileEvidence:
    frames: list[AcsFrameEvidence] = []
    for frame in page.frames[:10]:
        frames.append(
            AcsFrameEvidence(
                url=_safe_url(frame.url),
                text_prefix=await _frame_text_prefix(frame),
                visible_fields=tuple(await _visible_field_metadata_for_frame(frame)),
            )
        )
    return AcsProfileEvidence(
        brand=brand,
        title=await page.title(),
        final_url=_safe_url(page.url),
        frames=tuple(frames),
    )


async def _frame_text_prefix(frame: Frame) -> str:
    try:
        text = await frame.locator("body").inner_text(timeout=1_000)
    except PlaywrightError:
        return ""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:1000]


async def _visible_field_metadata_for_frame(frame: Frame) -> list[AcsFieldEvidence]:
    fields: list[AcsFieldEvidence] = []
    locators = frame.locator("input, button, select, a, [role='button']")
    count = min(await locators.count(), 20)
    for index in range(count):
        locator = locators.nth(index)
        try:
            if not await locator.is_visible(timeout=500):
                continue
            fields.append(
                AcsFieldEvidence(
                    tag=await locator.evaluate("el => el.tagName.toLowerCase()"),
                    type=await locator.get_attribute("type"),
                    name=await locator.get_attribute("name"),
                    id=await locator.get_attribute("id"),
                    text=(await locator.inner_text(timeout=500))[:40],
                )
            )
        except PlaywrightError:
            continue
    return fields


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _same_origin_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_parts = urlsplit(left)
    right_parts = urlsplit(right)
    return (
        left_parts.scheme == right_parts.scheme
        and left_parts.netloc == right_parts.netloc
        and left_parts.path.rstrip("/") == right_parts.path.rstrip("/")
    )


def _html_with_base_url(html: str, *, form_base_url: str) -> str:
    if not form_base_url.strip() or "<base" in html.lower():
        return html
    if 'action="./' not in html and "action='./" not in html:
        return html
    base_tag = f'<base href="{form_base_url.rstrip("/")}/">'
    lowered = html.lower()
    head_index = lowered.find("<head>")
    if head_index >= 0:
        insert_at = head_index + len("<head>")
        return f"{html[:insert_at]}{base_tag}{html[insert_at:]}"
    return f"<head>{base_tag}</head>{html}"


def _has_auto_submit(html: str) -> bool:
    lowered = html.lower()
    return "onload" in lowered and ".submit(" in lowered
