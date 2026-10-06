# 🌐 SitePulse — Website Security & Uptime Monitor

A Python-based desktop application for monitoring website availability, response time, SSL/TLS certificates, and HTTP security headers.

## 📌 About

**SitePulse** is a cybersecurity-focused website monitoring tool developed using Python. It allows users to check the availability and basic security configuration of a website from a simple desktop GUI.

The application analyzes website response information, SSL/TLS certificates, and important HTTP security headers. It also supports automatic monitoring, check history, configurable settings, and PDF report generation.

## ✨ Features

* 🔍 Website availability checking
* 📊 HTTP status code detection
* ⚡ Response-time measurement
* 🌐 IP address and server information
* 🔐 SSL/TLS certificate analysis
* 📅 Certificate expiration and remaining-days check
* 🛡️ HTTP security-header audit
* 📈 Security-header score
* ⏱️ Automatic website monitoring
* 📜 Check history
* ⚙️ Configurable monitoring and certificate settings
* 📄 PDF report generation

## 🛡️ Security Headers Checked

SitePulse checks the following six HTTP security headers:

| Header                      | Purpose                              |
| --------------------------- | ------------------------------------ |
| `Strict-Transport-Security` | Enforces HTTPS                       |
| `Content-Security-Policy`   | Helps reduce XSS-related risks       |
| `X-Frame-Options`           | Helps prevent clickjacking           |
| `X-Content-Type-Options`    | Prevents MIME sniffing               |
| `Referrer-Policy`           | Controls referrer information        |
| `Permissions-Policy`        | Controls browser feature permissions |

The application calculates a score based on the number of supported headers detected.

## 🛠️ Technologies Used

* **Python 3**
* **Tkinter** — Desktop GUI
* **Requests** — HTTP requests
* **BeautifulSoup** — HTML parsing
* **SSL / Socket** — Network and certificate information
* **Pillow** — Image handling
* **ReportLab** — PDF report generation
* **JSON** — Local history and settings storage
* **Threading** — Background monitoring

## 📂 Project Structure

```text
SitePulse/
│
├── sitepulse_gui.py
├── sitepulse_history.json
├── sitepulse_settings.json
├── sitepulse_report_*.pdf
└── README.md
```

## 🚀 Installation

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/SitePulse-Website-Security-Uptime-Monitor.git
cd SitePulse-Website-Security-Uptime-Monitor
```

Install the required packages:

```bash
pip install requests beautifulsoup4 pillow reportlab
```

Run the application:

```bash
python sitepulse_gui.py
```

## ▶️ Usage

1. Launch SitePulse.
2. Enter a website URL.
3. Click **Check Website**.
4. Review the website availability and response information.
5. Open the **Security** section to view SSL/TLS and security-header results.
6. Start **Auto-Monitoring** if continuous checking is required.
7. View previous checks through **History**.
8. Export the result as a PDF report.

## ⚙️ Configuration

SitePulse allows users to configure:

* Request timeout
* SSL certificate warning period
* Default monitoring interval

Settings are stored locally in:

```text
sitepulse_settings.json
```

Website check history is stored in:

```text
sitepulse_history.json
```

## 📄 Reporting

SitePulse can generate PDF reports containing:

* Website status
* HTTP status code
* Response time
* IP address
* Server information
* Website title
* SSL/TLS certificate information
* Security-header audit
* Security-header score

## 🔮 Future Improvements

* DNS security checks
* More security headers
* Uptime statistics and graphs
* Email notifications
* Certificate-expiration alerts
* CSV export
* Additional website security checks

## ⚠️ Disclaimer

SitePulse is intended for **educational, defensive, monitoring, and authorized security assessment purposes only**.

Only check websites that you own or have permission to assess.

## 👨‍💻 Author

**BharatPutta**

 Cybersecurity & Ethical Hacking Learner

---

⭐ If you find this project useful, consider giving the repository a star.

