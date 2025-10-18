import frappe

def after_install():
    # 1️⃣ Ensure CNT Settings exists
    if not frappe.db.exists("CNT Settings"):
        doc = frappe.new_doc("CNT Settings")
        doc.enable_cnt_automation = 1
        doc.auto_prefix_custom_fields = 1
        doc.cnt_app_color = "#0F9D58"
        doc.insert(ignore_permissions=True)

    # 2️⃣ Seed default Workflows, Roles, etc. if needed
    # e.g. create a CNT Workspace or link default icons

    # 3️⃣ Show a message in the console
    frappe.logger().info("CNT Tools successfully initialized.")