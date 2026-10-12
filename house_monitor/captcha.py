"""本地验证码识别封装；不调用第三方识别服务。"""
from .http import SourceError


class CaptchaSolver:
    def __init__(self):
        try:
            import ddddocr
        except ImportError as exc:
            raise SourceError("未安装 ddddocr，无法处理图片验证码", "dependency_missing") from exc
        self.ocr = ddddocr.DdddOcr(show_ad=False)

    def image(self, content):
        text = self.ocr.classification(content).strip()
        if not text:
            raise SourceError("ddddocr 未能识别图片验证码", "captcha_failed")
        return text

    def slider(self, target, background, simple_target=False):
        match = self.ocr.slide_match(target, background, simple_target=simple_target)
        try:
            return int(match["target"][0])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SourceError("ddddocr 未能识别滑块位置", "captcha_failed") from exc