# Google Forms Spammer (reworked)

A complete rework of UnidentifiedX's Google Forms Spammer. All code has been rewritten and optimized to improve reliability, usability and maintainability.

The original project was not maintained anymore, and had many limitations. This project aims to fix those limitations, while keeping the core functionality of spamming Google Forms.

Have a friend who had a naive goal of using google forms? Prank them by sending a million rickrolls right at them! No captchas can stop you now!

Unfortunately all of the original limitations could not be fixed, but many have been improved. Also I removed the html scraping part of the original project because it's pointless to this project. I also improved the way questions are identified and answered, making it more reliable. I don't think the original project worked for many forms. I tried it on questions with different types and it failed to even attempt parsing multi-choice/single-choice checkbox questions, so I had to write a completely new solution for that. I haven't tested my rework all that much, but it should work for most forms.

### New Features
- Rewritten codebase for better reliability and maintainability
- Improved question identification and answering system
- Multi-threaded requests for faster spamming
- Improved usability with better prompts and messages
- Supports Multiple Choice, Checkbox and Open-Ended questions

### Old Features
- Spam!
- Bypass xFanatical CAPTCHA by using Selenium to load the form first
- Answer required questions only
- Custom answers for questions (repeated for each response)
- Custom number of responses

### Limitations
- Cannot answer Google Forms that collect emails
- If the xFanatical CAPTCHA time runs out, you have to re-key everything (this may be patched in the future)
- Cannot answer forms with multiple pages
- Currently cannot answer forms with `<span>`s that are not questions (including images)
- **Important: Please enter the long version of the form link, i.e. it starts with `https://docs.google.com/forms` rather than `https://forms.gle`**

**Also very important: Use at your own risk. I do not encourage nor endorse any kind of activity that is illegal, causes harm to others, or is morally wrong.**

## How this works

This tool uses a hybrid approach to extract questions and submit answers reliably:

1) Fast “API-like” parse first
- It fetches the form HTML directly and looks for Google’s internal data blob (FB_PUBLIC_LOAD_DATA_), which contains a structured description of all questions. When available, this provides accurate question IDs, types, and options without opening a browser.

2) Smart browser fallback
- If the internal data isn’t present or is blocked, it opens the form in a real browser (Selenium). This lets you solve CAPTCHAs and ensures all dynamic content loads. The tool then parses the rendered page and collects any required hidden tokens.

3) Session reuse for submissions
- When a browser was used, the script reuses its cookies and User-Agent to mimic the same session for POST requests. It also includes hidden fields (like fbzx, fvv, pageHistory) so Google accepts the submission.

4) Guided answering with validation
- The console prompts you through each question with numbered options for Multiple Choice and Checkbox types, enforcing required fields and basic validation so you don’t submit invalid answers.

5) Concurrent submissions with progress
- Responses are sent concurrently with a small pool of threads. While running, the tool shows per‑thread start/finish messages and a live progress counter of attempts and successes.

### Requirements
- Python 3.7 or higher
- Required Python packages (install via `pip install -r requirements.txt`)
- A Google account (for CAPTCHA bypass)
- Basic knowledge of using the command line

### Note
- This tool is for educational and testing purposes only. Do not use it to spam or harass others. I am free of any responsibility for misuse of this tool. I am not liable for any consequences that may arise from using this tool. Use it responsibly and ethically.