import re
import json
import time
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import colorama
colorama.init()

class ConsoleColor:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
class QuestionType:
    OPEN = "Open Ended"
    MCQ = "Multiple Choice"
    CHECKBOX = "Checkbox"
@dataclass
class Question:
    id: str
    title: str
    required: bool
    type: str
    options: List[Tuple[str, str]] = field(default_factory=list)
def http_get(url: str) -> Optional[str]:
    """Fetch page HTML using a browser-like request; return text or None."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.text
        return None
    except requests.RequestException:
        return None
def selenium_get_html(url: str, interactive: bool = True) -> Tuple[Optional[str], Optional[List[dict]], Optional[str]]:
    """Load the form with Selenium. If interactive, allow user to solve CAPTCHA.
    Returns (html, cookies, user_agent)."""
    try:
        if interactive:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
            driver.get(url)
            input(
                f"{ConsoleColor.HEADER}Browser opened. Complete any CAPTCHA/manual steps, then press Enter here...{ConsoleColor.ENDC}"
            )
            html = driver.page_source
            ua = driver.execute_script("return navigator.userAgent")
            cookies = driver.get_cookies()
            driver.quit()
            return html, cookies, ua
        else:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.get(url)
            html = driver.page_source
            ua = driver.execute_script("return navigator.userAgent")
            cookies = driver.get_cookies()
            driver.quit()
            return html, cookies, ua
    except Exception as e:
        print(f"{ConsoleColor.FAIL}Selenium error: {e}{ConsoleColor.ENDC}")
        return None, None, None
def extract_hidden_tokens(html: str) -> Dict[str, str]:
    """Extract hidden form fields like fvv, fbzx, pageHistory, etc."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    tokens: Dict[str, str] = {}
    if not form:
        return tokens
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        value = inp.get("value", "")
        if inp.get("type") == "hidden" or name in ("fvv", "fbzx", "pageHistory", "continue"):
            tokens[name] = value
    for ta in form.find_all("textarea"):
        name = ta.get("name")
        if name:
            tokens[name] = ta.text or ta.get("value", "")
    return tokens
def parse_questions_from_internal_data(html: str) -> List[Question]:
    """Try to parse questions from FB_PUBLIC_LOAD_DATA_ variable."""
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    data_blob = None
    for s in scripts:
        content = s.string or ""
        if "FB_PUBLIC_LOAD_DATA_" in content:
            m = re.search(r"var FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*$", content, re.S | re.M)
            if m:
                data_blob = m.group(1)
                break
    if not data_blob:
        return []
    try:
        data = json.loads(data_blob)
    except json.JSONDecodeError:
        return []
    items = None
    try:
        items = data[1][1]
    except Exception:
        try:
            items = data[1]
        except Exception:
            items = None
    if not isinstance(items, list):
        return []
    questions: List[Question] = []
    for it in items:
        try:
            title = it[1]
            meta = it[4][0]
            entry_id = meta[0]
            required = meta[2] == 1 if len(meta) > 2 else False
            raw_options = meta[1]
            qtype_flag = it[3]
            qid = f"entry.{entry_id}"
            if not raw_options:
                questions.append(Question(id=qid, title=title, required=required, type=QuestionType.OPEN))
            else:
                opts: List[Tuple[str, str]] = []
                for opt in raw_options:
                    if isinstance(opt, list) and opt:
                        label = str(opt[0])
                        opts.append((label, label))
                if qtype_flag == 4:
                    qtype = QuestionType.CHECKBOX
                else:
                    qtype = QuestionType.MCQ
                questions.append(Question(id=qid, title=title, required=required, type=qtype, options=opts))
        except Exception:
            continue
    return questions
def parse_questions_from_html(html: str) -> List[Question]:
    """Fallback HTML scraper for questions and IDs."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("div", {"role": "listitem"})
    questions: List[Question] = []
    for b in blocks:
        title_div = b.find("div", {"role": "heading"})
        if not title_div:
            continue
        title = title_div.get_text(strip=True)
        required = bool(b.find("span", {"aria-label": "Required question"}))
        dp = b.find("div", attrs={"data-params": True})
        entry_id = None
        if dp and dp.has_attr("data-params"):
            m = re.search(r"\[\[(\d+),", dp["data-params"])
            if m:
                entry_id = m.group(1)
        if not entry_id:
            name_input = b.find(["input", "textarea"], attrs={"name": re.compile(r"^entry\\.")})
            if name_input and name_input.has_attr("name"):
                entry_id = name_input["name"].split(".")[-1]
        if not entry_id:
            continue
        qid = f"entry.{entry_id}"
        radios = b.find_all("div", {"role": "radio"})
        checks = b.find_all("div", {"role": "checkbox"})
        textarea = b.find("textarea")
        text_input = b.find("input", {"type": "text"})
        if radios:
            opts: List[Tuple[str, str]] = []
            for r in b.find_all(attrs={"data-value": True}):
                val = r.get("data-value", "").strip()
                if val:
                    opts.append((val, val))
            if not opts:
                for r in radios:
                    label = r.get("aria-label") or r.get_text(strip=True)
                    opts.append((label, label))
            questions.append(Question(id=qid, title=title, required=required, type=QuestionType.MCQ, options=opts))
        elif checks:
            opts = []
            for c in b.find_all(attrs={"data-value": True}):
                val = c.get("data-value", "").strip()
                if val:
                    opts.append((val, val))
            if not opts:
                for c in checks:
                    label = c.get("aria-label") or c.get_text(strip=True)
                    opts.append((label, label))
            questions.append(Question(id=qid, title=title, required=required, type=QuestionType.CHECKBOX, options=opts))
        elif textarea or text_input:
            questions.append(Question(id=qid, title=title, required=required, type=QuestionType.OPEN))
        else:
            continue
    return questions
def build_payload(hidden: Dict[str, str], answers: Dict[str, object]) -> List[Tuple[str, str]]:
    """Build a list of (key, value) pairs for submission, including hidden tokens."""
    payload: List[Tuple[str, str]] = []
    for k, v in hidden.items():
        payload.append((k, v))
    for k, v in answers.items():
        if isinstance(v, list):
            for item in v:
                payload.append((k, str(item)))
        else:
            payload.append((k, str(v)))
    return payload
def build_session(url: str, cookies: Optional[List[dict]], user_agent: Optional[str]) -> Tuple[requests.Session, Dict[str, str]]:
    """Build a requests session reusing Selenium cookies and UA if provided."""
    sess = requests.Session()
    headers = {
        "User-Agent": user_agent
        or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        ),
        "Referer": url,
    }
    sess.headers.update(headers)
    if cookies:
        for c in cookies:
            try:
                sess.cookies.set(c.get("name"), c.get("value"), domain=c.get("domain"))
            except Exception:
                sess.cookies.set(c.get("name"), c.get("value"))
    return sess, headers
def ask_user_for_answers(questions: List[Question]) -> Dict[str, object]:
    answers: Dict[str, object] = {}
    print(f"\n{ConsoleColor.OKCYAN}--- Answer the questions below ---{ConsoleColor.ENDC}")
    for idx, q in enumerate(questions, start=1):
        req_mark = " *" if q.required else ""
        print(f"\n{ConsoleColor.OKGREEN}Q{idx}:{ConsoleColor.ENDC} {q.title}{req_mark}")
        if q.type == QuestionType.OPEN:
            while True:
                prompt = "Enter your answer" + (" (optional)" if not q.required else "")
                print(ConsoleColor.HEADER + prompt + ConsoleColor.ENDC)
                ans = input("> ")
                if ans or not q.required:
                    answers[q.id] = ans
                    break
                print(f"{ConsoleColor.FAIL}This question is required.{ConsoleColor.ENDC}")
        elif q.type == QuestionType.MCQ:
            for i, (label, _) in enumerate(q.options, start=1):
                print(f"  {i}. {label}")
            while True:
                prompt = f"Choose 1-{len(q.options)}" + (" (optional)" if not q.required else "")
                print(ConsoleColor.HEADER + prompt + ConsoleColor.ENDC)
                raw = input("> ").strip()
                if not raw and not q.required:
                    answers[q.id] = ""
                    break
                try:
                    n = int(raw)
                    if 1 <= n <= len(q.options):
                        answers[q.id] = q.options[n - 1][1]
                        break
                except ValueError:
                    pass
                print(f"{ConsoleColor.FAIL}Invalid selection.{ConsoleColor.ENDC}")
        elif q.type == QuestionType.CHECKBOX:
            for i, (label, _) in enumerate(q.options, start=1):
                print(f"  {i}. {label}")
            while True:
                prompt = f"Choose numbers like 1,3" + (" (optional)" if not q.required else "")
                print(ConsoleColor.HEADER + prompt + ConsoleColor.ENDC)
                raw = input("> ").strip()
                if not raw and not q.required:
                    answers[q.id] = []
                    break
                try:
                    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
                    if not parts and not q.required:
                        answers[q.id] = []
                        break
                    if all(1 <= p <= len(q.options) for p in parts):
                        answers[q.id] = [q.options[p - 1][1] for p in parts]
                        break
                except ValueError:
                    pass
                print(f"{ConsoleColor.FAIL}Invalid input.{ConsoleColor.ENDC}")
    return answers
def submit_form(url: str, payload: List[Tuple[str, str]], times: int, sess: Optional[requests.Session] = None, headers: Optional[Dict[str, str]] = None) -> int:
    """Submit the form 'times' times with progress output and threading.
    Can reuse a provided requests Session and headers (cookies/UA)."""
    submit_url = url.replace("/viewform", "/formResponse")
    attempted = 0
    success = 0
    lock = threading.Lock()
    if sess is None:
        sess = requests.Session()
    if headers is None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            ),
            "Referer": url,
        }
    def worker(idx: int, n: int):
        nonlocal attempted, success
        print(f"{ConsoleColor.OKBLUE}[Thread {idx}] Starting with {n} requests...{ConsoleColor.ENDC}", flush=True)
        local_success = 0
        for _ in range(n):
            try:
                r = sess.post(submit_url, data=payload, headers=headers, timeout=15, allow_redirects=False)
                with lock:
                    attempted += 1
                if r.status_code in (200, 302):
                    local_success += 1
            except requests.RequestException:
                with lock:
                    attempted += 1
        with lock:
            success += local_success
        print(
            f"{ConsoleColor.OKBLUE}[Thread {idx}] Finished. Success: {local_success}/{n}{ConsoleColor.ENDC}",
            flush=True,
        )
    thread_count = min(10, max(1, times))
    base = times // thread_count
    rem = times % thread_count
    print(
        f"{ConsoleColor.OKCYAN}Starting submissions: {times} total using {thread_count} threads...{ConsoleColor.ENDC}",
        flush=True,
    )
    threads = []
    for i in range(thread_count):
        n = base + (1 if i < rem else 0)
        if n <= 0:
            continue
        t = threading.Thread(target=worker, args=(i + 1, n), daemon=True)
        threads.append(t)
        t.start()
    def monitor():
        last_report = -1
        while any(t.is_alive() for t in threads):
            with lock:
                att, suc = attempted, success
            if att != last_report:
                print(
                    f"{ConsoleColor.OKCYAN}Progress: {att}/{times} attempts{ConsoleColor.ENDC}",
                    flush=True,
                )
                last_report = att
            time.sleep(0.5)
        with lock:
            att, suc = attempted, success
        print(
            f"{ConsoleColor.OKCYAN}Progress: {att}/{times} attempts{ConsoleColor.ENDC}",
            flush=True,
        )
    mon = threading.Thread(target=monitor, daemon=True)
    mon.start()
    for t in threads:
        t.join()
    mon.join(timeout=0.1)
    if success == 0:
        try:
            test = sess.post(submit_url, data=payload, headers=headers, timeout=20, allow_redirects=False)
            snippet = (test.text or "")[:400].replace("\n", " ")
            print(
                f"{ConsoleColor.WARNING}Diagnostic: status={test.status_code}, location={test.headers.get('Location')}, body[0:400]={snippet}{ConsoleColor.ENDC}"
            )
        except Exception as e:
            print(f"{ConsoleColor.WARNING}Diagnostic request failed: {e}{ConsoleColor.ENDC}")
    return success
def main():
    while True:
        print(f"\n{ConsoleColor.HEADER}Enter Google Form URL (or 'exit'): {ConsoleColor.ENDC}")
        url = input("> ").strip()
        if not url:
            continue
        if url.lower() == "exit":
            break
        html = http_get(url)
        cookies = None
        user_agent = None
        if not html or "FB_PUBLIC_LOAD_DATA_" not in html:
            print(f"{ConsoleColor.WARNING}Direct fetch missing internal data; falling back to browser...{ConsoleColor.ENDC}")
            html, cookies, user_agent = selenium_get_html(url, interactive=True)
        if not html:
            print(f"{ConsoleColor.FAIL}Failed to load form HTML.{ConsoleColor.ENDC}")
            continue
        questions = parse_questions_from_internal_data(html)
        if not questions:
            questions = parse_questions_from_html(html)
        if not questions:
            print(f"{ConsoleColor.FAIL}Could not detect any questions in the form.{ConsoleColor.ENDC}")
            continue
        hidden_tokens = extract_hidden_tokens(html)
        answers = ask_user_for_answers(questions)
        print(f"\n{ConsoleColor.OKCYAN}--- Review ---{ConsoleColor.ENDC}")
        for q in questions:
            a = answers.get(q.id, "")
            disp = ", ".join(a) if isinstance(a, list) else a
            print(f"{ConsoleColor.OKGREEN}{q.title}:{ConsoleColor.ENDC} {disp if disp else '(empty)'}")
        confirm = input(f"\n{ConsoleColor.HEADER}Submit these answers? (y/n): {ConsoleColor.ENDC}").strip().lower()
        if confirm != "y":
            print(f"{ConsoleColor.WARNING}Cancelled.{ConsoleColor.ENDC}")
            continue
        payload = build_payload(hidden_tokens, answers)
        while True:
            try:
                times = int(input(ConsoleColor.HEADER + "How many times to submit?: " + ConsoleColor.ENDC))
                if times < 1:
                    print(f"{ConsoleColor.FAIL}Enter a positive integer.{ConsoleColor.ENDC}")
                    continue
                break
            except ValueError:
                print(f"{ConsoleColor.FAIL}Please enter a valid integer.{ConsoleColor.ENDC}")
        sess, headers = build_session(url, cookies, user_agent)
        start = time.time()
        success = submit_form(url, payload, times, sess=sess, headers=headers)
        dur = time.time() - start
        print(
            f"{ConsoleColor.OKGREEN}Complete! Sent {times} requests, "
            f"({success} successful, {times - success} unsuccessful) in {dur:.2f}s.{ConsoleColor.ENDC}"
        )
if __name__ == "__main__":
    main()

on
import time
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import colorama
colorama.init()

class ConsoleColor:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
class QuestionType:
    OPEN = "Open Ended"
    MCQ = "Multiple Choice"
    CHECKBOX = "Checkbox"
@dataclass
class Question:
    id: str
    title: str
    required: bool
    type: str
    options: List[Tuple[str, str]] = field(default_factory=list)
def http_get(url: str) -> Optional[str]:
    """Fetch page HTML using a browser-like request; return text or None."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.text
        return None
    except requests.RequestException:
        return None
def selenium_get_html(url: str, interactive: bool = True) -> Tuple[Optional[str], Optional[List[dict]], Optional[str]]:
    """Load the form with Selenium. If interactive, allow user to solve CAPTCHA.
    Returns (html, cookies, user_agent)."""
    try:
        if interactive:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
            driver.get(url)
            input(
                f"{ConsoleColor.HEADER}Browser opened. Complete any CAPTCHA/manual steps, then press Enter here...{ConsoleColor.ENDC}"
            )
            html = driver.page_source
            ua = driver.execute_script("return navigator.userAgent")
            cookies = driver.get_cookies()
            driver.quit()
            return html, cookies, ua
        else:
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.get(url)
            html = driver.page_source
            ua = driver.execute_script("return navigator.userAgent")
            cookies = driver.get_cookies()
            driver.quit()
            return html, cookies, ua
    except Exception as e:
        print(f"{ConsoleColor.FAIL}Selenium error: {e}{ConsoleColor.ENDC}")
        return None, None, None
def extract_hidden_tokens(html: str) -> Dict[str, str]:
    """Extract hidden form fields like fvv, fbzx, pageHistory, etc."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    tokens: Dict[str, str] = {}
    if not form:
        return tokens
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        value = inp.get("value", "")
        if inp.get("type") == "hidden" or name in ("fvv", "fbzx", "pageHistory", "continue"):
            tokens[name] = value
    for ta in form.find_all("textarea"):
        name = ta.get("name")
        if name:
            tokens[name] = ta.text or ta.get("value", "")
    return tokens
def parse_questions_from_internal_data(html: str) -> List[Question]:
    """Try to parse questions from FB_PUBLIC_LOAD_DATA_ variable."""
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    data_blob = None
    for s in scripts:
        content = s.string or ""
        if "FB_PUBLIC_LOAD_DATA_" in content:
            m = re.search(r"var FB_PUBLIC_LOAD_DATA_\s*=\s*(.*?);\s*$", content, re.S | re.M)
            if m:
                data_blob = m.group(1)
                break
    if not data_blob:
        return []
    try:
        data = json.loads(data_blob)
    except json.JSONDecodeError:
        return []
    items = None
    try:
        items = data[1][1]
    except Exception:
        try:
            items = data[1]
        except Exception:
            items = None
    if not isinstance(items, list):
        return []
    questions: List[Question] = []
    for it in items:
        try:
            title = it[1]
            meta = it[4][0]
            entry_id = meta[0]
            required = meta[2] == 1 if len(meta) > 2 else False
            raw_options = meta[1]
            qtype_flag = it[3]
            qid = f"entry.{entry_id}"
            if not raw_options:
                questions.append(Question(id=qid, title=title, required=required, type=QuestionType.OPEN))
            else:
                opts: List[Tuple[str, str]] = []
                for opt in raw_options:
                    if isinstance(opt, list) and opt:
                        label = str(opt[0])
                        opts.append((label, label))
                if qtype_flag == 4:
                    qtype = QuestionType.CHECKBOX
                else:
                    qtype = QuestionType.MCQ
                questions.append(Question(id=qid, title=title, required=required, type=qtype, options=opts))
        except Exception:
            continue
    return questions
def parse_questions_from_html(html: str) -> List[Question]:
    """Fallback HTML scraper for questions and IDs."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("div", {"role": "listitem"})
    questions: List[Question] = []
    for b in blocks:
        title_div = b.find("div", {"role": "heading"})
        if not title_div:
            continue
        title = title_div.get_text(strip=True)
        required = bool(b.find("span", {"aria-label": "Required question"}))
        dp = b.find("div", attrs={"data-params": True})
        entry_id = None
        if dp and dp.has_attr("data-params"):
            m = re.search(r"\[\[(\d+),", dp["data-params"])
            if m:
                entry_id = m.group(1)
        if not entry_id:
            name_input = b.find(["input", "textarea"], attrs={"name": re.compile(r"^entry\\.")})
            if name_input and name_input.has_attr("name"):
                entry_id = name_input["name"].split(".")[-1]
        if not entry_id:
            continue
        qid = f"entry.{entry_id}"
        radios = b.find_all("div", {"role": "radio"})
        checks = b.find_all("div", {"role": "checkbox"})
        textarea = b.find("textarea")
        text_input = b.find("input", {"type": "text"})
        if radios:
            opts: List[Tuple[str, str]] = []
            for r in b.find_all(attrs={"data-value": True}):
                val = r.get("data-value", "").strip()
                if val:
                    opts.append((val, val))
            if not opts:
                for r in radios:
                    label = r.get("aria-label") or r.get_text(strip=True)
                    opts.append((label, label))
            questions.append(Question(id=qid, title=title, required=required, type=QuestionType.MCQ, options=opts))
        elif checks:
            opts = []
            for c in b.find_all(attrs={"data-value": True}):
                val = c.get("data-value", "").strip()
                if val:
                    opts.append((val, val))
            if not opts:
                for c in checks:
                    label = c.get("aria-label") or c.get_text(strip=True)
                    opts.append((label, label))
            questions.append(Question(id=qid, title=title, required=required, type=QuestionType.CHECKBOX, options=opts))
        elif textarea or text_input:
            questions.append(Question(id=qid, title=title, required=required, type=QuestionType.OPEN))
        else:
            continue
    return questions
def build_payload(hidden: Dict[str, str], answers: Dict[str, object]) -> List[Tuple[str, str]]:
    """Build a list of (key, value) pairs for submission, including hidden tokens."""
    payload: List[Tuple[str, str]] = []
    for k, v in hidden.items():
        payload.append((k, v))
    for k, v in answers.items():
        if isinstance(v, list):
            for item in v:
                payload.append((k, str(item)))
        else:
            payload.append((k, str(v)))
    return payload
def build_session(url: str, cookies: Optional[List[dict]], user_agent: Optional[str]) -> Tuple[requests.Session, Dict[str, str]]:
    """Build a requests session reusing Selenium cookies and UA if provided."""
    sess = requests.Session()
    headers = {
        "User-Agent": user_agent
        or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        ),
        "Referer": url,
    }
    sess.headers.update(headers)
    if cookies:
        for c in cookies:
            try:
                sess.cookies.set(c.get("name"), c.get("value"), domain=c.get("domain"))
            except Exception:
                sess.cookies.set(c.get("name"), c.get("value"))
    return sess, headers
def ask_user_for_answers(questions: List[Question]) -> Dict[str, object]:
    answers: Dict[str, object] = {}
    print(f"\n{ConsoleColor.OKCYAN}--- Answer the questions below ---{ConsoleColor.ENDC}")
    for idx, q in enumerate(questions, start=1):
        req_mark = " *" if q.required else ""
        print(f"\n{ConsoleColor.OKGREEN}Q{idx}:{ConsoleColor.ENDC} {q.title}{req_mark}")
        if q.type == QuestionType.OPEN:
            while True:
                prompt = "Enter your answer" + (" (optional)" if not q.required else "")
                print(ConsoleColor.HEADER + prompt + ConsoleColor.ENDC)
                ans = input("> ")
                if ans or not q.required:
                    answers[q.id] = ans
                    break
                print(f"{ConsoleColor.FAIL}This question is required.{ConsoleColor.ENDC}")
        elif q.type == QuestionType.MCQ:
            for i, (label, _) in enumerate(q.options, start=1):
                print(f"  {i}. {label}")
            while True:
                prompt = f"Choose 1-{len(q.options)}" + (" (optional)" if not q.required else "")
                print(ConsoleColor.HEADER + prompt + ConsoleColor.ENDC)
                raw = input("> ").strip()
                if not raw and not q.required:
                    answers[q.id] = ""
                    break
                try:
                    n = int(raw)
                    if 1 <= n <= len(q.options):
                        answers[q.id] = q.options[n - 1][1]
                        break
                except ValueError:
                    pass
                print(f"{ConsoleColor.FAIL}Invalid selection.{ConsoleColor.ENDC}")
        elif q.type == QuestionType.CHECKBOX:
            for i, (label, _) in enumerate(q.options, start=1):
                print(f"  {i}. {label}")
            while True:
                prompt = f"Choose numbers like 1,3" + (" (optional)" if not q.required else "")
                print(ConsoleColor.HEADER + prompt + ConsoleColor.ENDC)
                raw = input("> ").strip()
                if not raw and not q.required:
                    answers[q.id] = []
                    break
                try:
                    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
                    if not parts and not q.required:
                        answers[q.id] = []
                        break
                    if all(1 <= p <= len(q.options) for p in parts):
                        answers[q.id] = [q.options[p - 1][1] for p in parts]
                        break
                except ValueError:
                    pass
                print(f"{ConsoleColor.FAIL}Invalid input.{ConsoleColor.ENDC}")
    return answers
def submit_form(url: str, payload: List[Tuple[str, str]], times: int, sess: Optional[requests.Session] = None, headers: Optional[Dict[str, str]] = None) -> int:
    """Submit the form 'times' times with progress output and threading.
    Can reuse a provided requests Session and headers (cookies/UA)."""
    submit_url = url.replace("/viewform", "/formResponse")
    attempted = 0
    success = 0
    lock = threading.Lock()
    if sess is None:
        sess = requests.Session()
    if headers is None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
            ),
            "Referer": url,
        }
    def worker(idx: int, n: int):
        nonlocal attempted, success
        print(f"{ConsoleColor.OKBLUE}[Thread {idx}] Starting with {n} requests...{ConsoleColor.ENDC}", flush=True)
        local_success = 0
        for _ in range(n):
            try:
                r = sess.post(submit_url, data=payload, headers=headers, timeout=15, allow_redirects=False)
                with lock:
                    attempted += 1
                if r.status_code in (200, 302):
                    local_success += 1
            except requests.RequestException:
                with lock:
                    attempted += 1
        with lock:
            success += local_success
        print(
            f"{ConsoleColor.OKBLUE}[Thread {idx}] Finished. Success: {local_success}/{n}{ConsoleColor.ENDC}",
            flush=True,
        )
    thread_count = min(10, max(1, times))
    base = times // thread_count
    rem = times % thread_count
    print(
        f"{ConsoleColor.OKCYAN}Starting submissions: {times} total using {thread_count} threads...{ConsoleColor.ENDC}",
        flush=True,
    )
    threads = []
    for i in range(thread_count):
        n = base + (1 if i < rem else 0)
        if n <= 0:
            continue
        t = threading.Thread(target=worker, args=(i + 1, n), daemon=True)
        threads.append(t)
        t.start()
    def monitor():
        last_report = -1
        while any(t.is_alive() for t in threads):
            with lock:
                att, suc = attempted, success
            if att != last_report:
                print(
                    f"{ConsoleColor.OKCYAN}Progress: {att}/{times} attempts{ConsoleColor.ENDC}",
                    flush=True,
                )
                last_report = att
            time.sleep(0.5)
        with lock:
            att, suc = attempted, success
        print(
            f"{ConsoleColor.OKCYAN}Progress: {att}/{times} attempts{ConsoleColor.ENDC}",
            flush=True,
        )
    mon = threading.Thread(target=monitor, daemon=True)
    mon.start()
    for t in threads:
        t.join()
    mon.join(timeout=0.1)
    if success == 0:
        try:
            test = sess.post(submit_url, data=payload, headers=headers, timeout=20, allow_redirects=False)
            snippet = (test.text or "")[:400].replace("\n", " ")
            print(
                f"{ConsoleColor.WARNING}Diagnostic: status={test.status_code}, location={test.headers.get('Location')}, body[0:400]={snippet}{ConsoleColor.ENDC}"
            )
        except Exception as e:
            print(f"{ConsoleColor.WARNING}Diagnostic request failed: {e}{ConsoleColor.ENDC}")
    return success
def main():
    while True:
        print(f"\n{ConsoleColor.HEADER}Enter Google Form URL (or 'exit'): {ConsoleColor.ENDC}")
        url = input("> ").strip()
        if not url:
            continue
        if url.lower() == "exit":
            break
        html = http_get(url)
        cookies = None
        user_agent = None
        if not html or "FB_PUBLIC_LOAD_DATA_" not in html:
            print(f"{ConsoleColor.WARNING}Direct fetch missing internal data; falling back to browser...{ConsoleColor.ENDC}")
            html, cookies, user_agent = selenium_get_html(url, interactive=True)
        if not html:
            print(f"{ConsoleColor.FAIL}Failed to load form HTML.{ConsoleColor.ENDC}")
            continue
        questions = parse_questions_from_internal_data(html)
        if not questions:
            questions = parse_questions_from_html(html)
        if not questions:
            print(f"{ConsoleColor.FAIL}Could not detect any questions in the form.{ConsoleColor.ENDC}")
            continue
        hidden_tokens = extract_hidden_tokens(html)
        answers = ask_user_for_answers(questions)
        print(f"\n{ConsoleColor.OKCYAN}--- Review ---{ConsoleColor.ENDC}")
        for q in questions:
            a = answers.get(q.id, "")
            disp = ", ".join(a) if isinstance(a, list) else a
            print(f"{ConsoleColor.OKGREEN}{q.title}:{ConsoleColor.ENDC} {disp if disp else '(empty)'}")
        confirm = input(f"\n{ConsoleColor.HEADER}Submit these answers? (y/n): {ConsoleColor.ENDC}").strip().lower()
        if confirm != "y":
            print(f"{ConsoleColor.WARNING}Cancelled.{ConsoleColor.ENDC}")
            continue
        payload = build_payload(hidden_tokens, answers)
        while True:
            try:
                times = int(input(ConsoleColor.HEADER + "How many times to submit?: " + ConsoleColor.ENDC))
                if times < 1:
                    print(f"{ConsoleColor.FAIL}Enter a positive integer.{ConsoleColor.ENDC}")
                    continue
                break
            except ValueError:
                print(f"{ConsoleColor.FAIL}Please enter a valid integer.{ConsoleColor.ENDC}")
        sess, headers = build_session(url, cookies, user_agent)
        start = time.time()
        success = submit_form(url, payload, times, sess=sess, headers=headers)
        dur = time.time() - start
        print(
            f"{ConsoleColor.OKGREEN}Complete! Sent {times} requests, "
            f"({success} successful, {times - success} unsuccessful) in {dur:.2f}s.{ConsoleColor.ENDC}"
        )
if __name__ == "__main__":
    main()