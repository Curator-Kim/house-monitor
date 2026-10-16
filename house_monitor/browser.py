"""受控浏览器会话，用于公开查询页面的验证码与 JavaScript 数据接口。"""
import os
import shutil
from time import sleep
from urllib.parse import urlencode
from .http import SourceError, UA


class BrowserSession:
    def __init__(self, config):
        self.config = config
        self.driver = None
        self.wait = None

    def __enter__(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            raise SourceError("未安装 selenium，无法处理浏览器验证码", "dependency_missing") from exc
        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,1200")
        options.add_argument(f"--user-agent={UA}")
        driver_path = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
        if driver_path:
            from selenium.webdriver.chrome.service import Service
            self.driver = webdriver.Chrome(service=Service(driver_path), options=options)
        else:
            self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, self.config.get("request_timeout_seconds", 20) + 20)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.driver is not None:
            self.driver.quit()

    def ygjy_search(self, url, district):
        from selenium.webdriver.common.by import By

        self.driver.get(url)
        button = self.wait.until(lambda d: d.find_element(By.ID, "checkCode"))
        self.wait.until(lambda d: (button.get_attribute("value") or "").strip())
        try:
            from .captcha import CaptchaSolver
            code = CaptchaSolver().image(button.screenshot_as_png).strip()
        except SourceError:
            code = (button.get_attribute("value") or "").strip()
        if not code:
            raise SourceError("阳光家缘验证码未生成或识别失败", "captcha_failed")
        self.driver.find_element(By.NAME, "sProjectAddress").send_keys(district)
        self.driver.find_element(By.NAME, "ValidateCode").send_keys(code)
        self.driver.find_element(By.ID, "btnSearch").click()

        def loaded(d):
            text = d.find_element(By.ID, "formTable").text
            rows = d.find_elements(By.CSS_SELECTOR, "#formTable tbody tr")
            return "数据加载中" not in text and ("暂无数据" in text or bool(rows))
        self.wait.until(loaded)
        return code

    def fetch_json(self, base_url, params, method="POST"):
        query = urlencode(params)
        url = base_url + ("&" if "?" in base_url else "?") + query
        script = """
        const url = arguments[0];
        const method = arguments[1];
        const done = arguments[arguments.length - 1];
        fetch(url, {method: method, credentials: 'same-origin'})
          .then(async response => done({status: response.status, url: response.url, text: await response.text()}))
          .catch(error => done({error: String(error)}));
        """
        result = self.driver.execute_async_script(script, url, method)
        if result.get("error"):
            raise SourceError(f"浏览器接口请求失败：{result['error']}")
        if result.get("status") != 200:
            raise SourceError(f"浏览器接口返回 HTTP {result.get('status')}")
        return result["text"]

    def drag_slider_to_end(self, url, retries=3):
        """处理页面提供的简单拖动验证；仅在验证元素明确存在时执行。"""
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.by import By

        for _ in range(retries):
            self.driver.get(url)
            handler = self.wait.until(lambda d: d.find_element(By.CSS_SELECTOR, ".handler"))
            slider = self.driver.find_element(By.ID, "slider")
            offset = slider.size["width"] - handler.size["width"]
            ActionChains(self.driver).click_and_hold(handler).move_by_offset(offset, 0).pause(0.2).release().perform()
            sleep(0.5)
            if "check.3g.fang.com" not in self.driver.current_url:
                return self.driver.get_cookies()
        raise SourceError("拖动验证未通过", "captcha_failed")