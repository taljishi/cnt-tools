/*******************************************************
 * Doctype Script:     Sales Return
 * Maintained By:      Cloud Nine Technologies
 * Description:        Auto-fetches address, creates credit note, and supports barcode-based item entry
 * Version:            v1.0
 * Last Updated:       2025-05-08
 *******************************************************/

// ─────────────────────────────────────
// SECTION 1: MAIN DOCTYPE EVENTS (Sales Return)
// ─────────────────────────────────────
frappe.ui.form.on('Sales Return', {
    customer(frm) {
        if (frm.doc.customer) {
            frm.set_query('shipping_address_name', () => ({
                filters: { link_name: frm.doc.customer }
            }));
        }
    },

    shipping_address_name(frm) {
        if (frm.doc.shipping_address_name) {
            return frm.call({
                method: "frappe.contacts.doctype.address.address.get_address_display",
                args: {
                    address_dict: frm.doc.shipping_address_name
                },
                callback(r) {
                    if (r.message) {
                        frm.set_value('customer_address_display', r.message);
                    }
                }
            });
        } else {
            frm.set_value("customer_address_display", "");
        }
    },

    refresh(frm) {
        if (!frm.is_new() && frm.doc.workflow_state !== "Credit Note Issued") {
            frm.add_custom_button(__('Create Credit Note'), function () {
                if (!frm.doc.customer || !frm.doc.items || frm.doc.items.length === 0) {
                    frappe.msgprint(__('Please select a customer and add at least one item.'));
                    return;
                }

                const invoice_items = frm.doc.items.map(row => {
                    const qty = row.qty > 0 ? -1 * row.qty : row.qty;
                    return {
                        item_code: row.item_code,
                        qty: qty,
                        batch_no: row.batch_no,
                        custom_sales_return: frm.doc.name
                    };
                });

                const to_date = frappe.datetime.now_date();
                const invoice_data = {
                    doctype: "Sales Invoice",
                    naming_series: "SI-RET-.YY",
                    customer: frm.doc.customer,
                    posting_date: to_date,
                    is_return: 1,
                    items: invoice_items,
                    remarks: `Credit Note for Sales Return: ${frm.doc.name}`,
                    po_no: frm.doc.customer_reference_no,
                    po_date: frm.doc.customer_reference_date,
                    shipping_address_name: frm.doc.shipping_address_name,
                    selling_price_list: frm.doc.selling_price_list,
                    select_print_heading: "Credit Note"
                };

                frappe.call({
                    method: "frappe.client.insert",
                    args: { doc: invoice_data },
                    callback(r) {
                        if (r.message) {
                            frappe.msgprint({
                                title: __('Credit Note Created'),
                                message: __('Sales Invoice {0} has been created successfully.', [r.message.name]),
                                indicator: 'green'
                            });
                            frappe.set_route('Form', 'Sales Invoice', r.message.name);
                        }
                    },
                    error(err) {
                        console.error("Credit Note creation failed:", err);
                        frappe.msgprint(__('An error occurred. Please check the console for details.'));
                    }
                });
            });
        }
    },

    scan_barcode(frm) {
        let raw_barcode = frm.doc.scan_barcode;
        if (!raw_barcode) return;

        const barcode = raw_barcode.trim();
        if (!barcode) {
            frappe.msgprint(__('Scanned barcode is empty.'));
            frm.set_value('scan_barcode', '');
            return;
        }

        frappe.call({
            method: "get_item_by_barcode", // custom server method if used
            args: { barcode },
            callback(r) {
                if (r.message) {
                    const item_code = r.message;
                    const existing = frm.doc.items.find(d => d.item_code === item_code);

                    if (existing) {
                        existing.qty += 1;
                    } else {
                        const new_row = frm.add_child('items');
                        new_row.item_code = item_code;
                        new_row.qty = 1;
                    }

                    frm.refresh_field('items');
                } else {
                    frappe.msgprint(__('No item found for barcode: {0}', [barcode]));
                }

                frm.set_value('scan_barcode', '');
            },
            error(err) {
                console.error('Barcode scan error:', err);
                frappe.msgprint(__('An error occurred while scanning. Please try again.'));
                frm.set_value('scan_barcode', '');
            }
        });
    }
});

// ─────────────────────────────────────
// SECTION 2: BATCH FILTERING (Items table)
// Filters batch_no by the row's item_code (and warehouse if present)
// Uses ERPNext's server-side query to respect expiry & posting date
// ─────────────────────────────────────

// Helper to (re)apply the query for the active row
function set_batch_query(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;

    // When opening the row dialog, ensure the link field picker is filtered
    frm.fields_dict.items.grid.get_field('batch_no').get_query = function () {
        return {
            query: 'erpnext.controllers.queries.get_batch_no',
            filters: {
                item_code: row.item_code,
                warehouse: row.warehouse || frm.doc.set_warehouse || undefined
            }
        };
    };
}

// Attach additional hooks without touching the existing ones above
frappe.ui.form.on('Sales Return', {
    onload(frm) {
        // Row-level list picker filtering, even before opening the row dialog
        frm.set_query('batch_no', 'items', function (doc, cdt, cdn) {
            const row = locals[cdt][cdn] || {};
            return {
                query: 'erpnext.controllers.queries.get_batch_no',
                filters: {
                    item_code: row.item_code,
                    warehouse: row.warehouse || doc.set_warehouse || undefined
                }
            };
        });
    },

    // When a grid row form is rendered, refresh its query
    items_on_form_rendered(frm) {
        const grid = frm.fields_dict.items.grid;
        const cdt = grid.doctype;
        const cdn = grid.get_selected && grid.get_selected()[0];
        if (cdn) set_batch_query(frm, cdt, cdn);
    }
});

// Replace child doctype name below with your exact child table doctype if different
frappe.ui.form.on('Sales Return Item', {
    item_code(frm, cdt, cdn) {
        // Clear stale batch when item changes
        frappe.model.set_value(cdt, cdn, 'batch_no', null);
        set_batch_query(frm, cdt, cdn);
    },
    warehouse(frm, cdt, cdn) {
        // Re-apply filtering when warehouse changes
        set_batch_query(frm, cdt, cdn);
    }
});