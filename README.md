# Maximus Tools

Maximus Tools is a custom ERPNext/Frappe app that provides a suite of operational utilities and process automation features built on top of ERPNext.  
It’s designed to streamline repetitive tasks, improve data consistency, and enhance overall efficiency across departments.

## 🚀 Features

- **Employee Checkin Automation**  
  Generate and manage Employee Checkins from external sources (e.g., biometric or access control systems) directly in ERPNext.

- **Bank Statement Formatter**  
  Parse, clean, and structure imported bank statement data for faster reconciliation and error-free statement runs.

- **Bill Creation Utilities**  
  Simplify supplier bill creation and mapping with flexible invoice run tools and rule-based invoice matching.

- **Invoice & Statement Processing**  
  Includes custom Doctypes like *Statement Run*, *Invoice Run*, and *Invoice Mapping* to handle recurring imports and automation of financial documents.

- **General ERP Extensions**  
  Contains supporting Client Scripts, Server Scripts, and Workflows for everyday operational automation.

## 🛠️ Installation

From your bench directory:

```bash
# Get the app
bench get-app https://github.com/taljishi/maximus-tools.git

# Install it on a site
bench --site your-site.local install-app maximus_tools
```

## 🧩 Compatibility
- **ERPNext:** v14+

## 📜 License

This project is licensed under the MIT License.
