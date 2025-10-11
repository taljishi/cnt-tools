from . import __version__ as app_version

app_name = "maximus_tools"
app_title = "Maximum Tools"
app_publisher = "Cloud Nine Technologies (CNT)"
app_description = "Tools for generating employee checkins, formatting bank statements, and craating of purchase invoices from supplier's bills"
app_email = "info@cnt.bh"
app_license = "MIT"
app_icon = "setting-gear"
app_color = "blue"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/maximus_tools/css/maximus_tools.css"
# app_include_js = "/assets/maximus_tools/js/maximus_tools.js"

# include js, css files in header of web template
# web_include_css = "/assets/maximus_tools/css/maximus_tools.css"
# web_include_js = "/assets/maximus_tools/js/maximus_tools.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "maximus_tools/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "maximus_tools.utils.jinja_methods",
#	"filters": "maximus_tools.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "maximus_tools.install.before_install"
# after_install = "maximus_tools.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "maximus_tools.uninstall.before_uninstall"
# after_uninstall = "maximus_tools.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "maximus_tools.utils.before_app_install"
# after_app_install = "maximus_tools.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "maximus_tools.utils.before_app_uninstall"
# after_app_uninstall = "maximus_tools.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "maximus_tools.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
#	"*": {
#		"on_update": "method",
#		"on_cancel": "method",
#		"on_trash": "method"
#	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
#	"all": [
#		"maximus_tools.tasks.all"
#	],
#	"daily": [
#		"maximus_tools.tasks.daily"
#	],
#	"hourly": [
#		"maximus_tools.tasks.hourly"
#	],
#	"weekly": [
#		"maximus_tools.tasks.weekly"
#	],
#	"monthly": [
#		"maximus_tools.tasks.monthly"
#	],
# }

# Testing
# -------

# before_tests = "maximus_tools.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "maximus_tools.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "maximus_tools.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["maximus_tools.utils.before_request"]
# after_request = ["maximus_tools.utils.after_request"]

# Job Events
# ----------
# before_job = ["maximus_tools.utils.before_job"]
# after_job = ["maximus_tools.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_3}",
#		"strict": False,
#	},
#	{
#		"doctype": "{doctype_4}"
#	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"maximus_tools.auth.validate"
# ]

# Export only what belongs to this app
fixtures = [
    # Doctypes that HAVE a "module" field
    {"dt": "Client Script",   "filters": [["module", "=", "Maximus Tools"]]},
    {"dt": "Print Format",    "filters": [["module", "=", "Maximus Tools"]]},
    {"dt": "Server Script",   "filters": [["module", "=", "Maximus Tools"]]},
    {"dt": "Notification",    "filters": [["module", "=", "Maximus Tools"]]},

    # Doctypes WITHOUT a "module" field → use naming convention
    {"dt": "Workflow",        "filters": [["name", "like", "Maximus %"]]},
    {"dt": "Workflow State",  "filters": [["name", "like", "Maximus %"]]},
    {"dt": "Workflow Action", "filters": [["name", "like", "Maximus %"]]},

    # Also no module: use a prefix you actually use in your CF/PS names
    {"dt": "Custom Field",    "filters": [["name", "like", "maximus_%"]]},
    {"dt": "Property Setter", "filters": [["name", "like", "maximus_%"]]},
]
