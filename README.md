# CNT Tools

**CNT Tools** is a collection of ERPNext extensions built to automate data imports, streamline integrations, and improve operational consistency across ERPNext environments.  
Developed by **Cloud Nine Technologies (CNT)** — it focuses on removing repetitive manual work and strengthening data accuracy.

## 🚀 Features

- **🕒 Employee Checkin Automation**  
  Generate and manage Employee Checkins from external sources (e.g., biometric or access control systems) directly in ERPNext.  
  Tested with **2N Access Unit M**. Export each device event CSV file, then import it into this tool to generate Employee Checkins automatically.

- **🏦 Bank Statement Formatter**  
  Parse, clean, and structure imported bank statement data for faster reconciliation and error-free statement runs.  
  Upload CSV bank statements and import them into ERPNext for validation and posting.

- **🚗 Fleet Management**
  Manage and track your organization’s fleet operations, including:
  - Fuel card tracking  
  - Fuel consumption logging  
  - Vehicle-linked workflows and maintenance visibility 

## 🛠️ Installation

From your bench directory:

```bash
# Get the app
bench get-app https://github.com/cnt-bh/cnt-tools.git

# Install it on a site
bench --site your-site.local install-app cnt_tools
```

### Notes

- Run `bench migrate` after installation to apply fixtures (e.g., custom fields, workspace, scripts).
- If updating an existing installation, pull the latest version and migrate:
  ```
  cd apps/cnt_tools
  git pull
  bench --site your-site.local migrate
  bench clear-cache
  ```
- Ensure SSH keys are configured if using private repositories.

## 🧩 Compatibility
- **ERPNext:** v14-v15
- **Frappe:** v14-v15

## 💫 Planned Features

- **Invoice Run**  
  A module for automated invoice creation and mapping.  
  Should support flexible import rules, field mapping, and error tracking for bulk invoice generation.

- **Enhanced Device Integration**  
  Extend the Employee Checkin Automation to support additional biometric and access control systems through API sync, not just file import.

## 👥 Maintainers

**Developed and maintained by:**  
[Cloud Nine Technologies (CNT)](https://cnt.bh)  
A Bahrain-based digital transformation company specializing in digital solutions and process automation.

## 📜 License

This project is licensed under the MIT License.
