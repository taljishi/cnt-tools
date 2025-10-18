/*******************************************************
 * Doctype Script:     Fuel Consumption
 * Maintained By:      Digital Transformation Team
 * Description:        Calculates total fuel and enables purchase invoice creation.
 *                     All fields are read-only except 'fuel_card_number' and 'amount_consumed',
 *                     which are controlled via field-level settings (Fetch From + editable).
 * Version:            v1.7
 * Last Updated:       2025-05-20
 *******************************************************/

// ─────────────────────────────────────
// SECTION 1: MAIN FORM EVENTS
// ─────────────────────────────────────
frappe.ui.form.on('Fuel Consumption', {
    refresh(frm) {
        calculate_total_fuel_consumption(frm);

        // Limit selectable fuel cards to 'In Use' only
        frm.fields_dict.fuel_consumption_details.grid.get_field('fuel_card_number').get_query = function(doc, cdt, cdn) {
            return {
                filters: { workflow_state: 'In Use' }
            };
        };
        
        // Filter shared_use_employee to Active only
        frm.fields_dict.fuel_consumption_details.grid.get_field('shared_use_employee').get_query = function(doc, cdt, cdn) {
            return {
                filters: { status: 'Active' }
            };
        };

        // Show 'Create Purchase Invoice' button only if not already invoiced
        if (frm.doc.docstatus === 1 && frm.doc.workflow_state !== "Purchase Invoice Created") {
            frm.add_custom_button(__('Create Purchase Invoice'), function () {
                create_purchase_invoice(frm);
            });
        }
    },

    validate(frm) {
        calculate_total_fuel_consumption(frm);
    }
});

// ─────────────────────────────────────
// SECTION 2: CHILD TABLE EVENTS
// ─────────────────────────────────────
frappe.ui.form.on('Fuel Consumption Details', {
    fuel_card_number(frm, cdt, cdn) {
        // Trigger fetch-from refresh only
        frm.fields_dict.fuel_consumption_details.grid.refresh();
    },

    amount_consumed(frm, cdt, cdn) {
        calculate_total_fuel_consumption(frm);
    },

    fuel_consumption_details_remove(frm) {
        calculate_total_fuel_consumption(frm);
    }
});

// ─────────────────────────────────────
// SECTION 3: TOTAL FUEL CALCULATION
// ─────────────────────────────────────
function calculate_total_fuel_consumption(frm) {
    let total = 0;
    (frm.doc.fuel_consumption_details || []).forEach(row => {
        total += flt(row.amount_consumed);
    });

    if (flt(frm.doc.total_fuel_consumption, 3) !== flt(total, 3)) {
        frm.set_value('total_fuel_consumption', total);
    }
}

// ─────────────────────────────────────
// SECTION 4: PURCHASE INVOICE CREATION
// ─────────────────────────────────────
async function create_purchase_invoice(frm) {
    const grouped = {};

    // Group by both cost_center and shared_use_cost_center
    (frm.doc.fuel_consumption_details || []).forEach(row => {
        const cost_center = row.cost_center || row.shared_use_cost_center;
        if (!cost_center) return;
        if (!grouped[cost_center]) grouped[cost_center] = 0;
        grouped[cost_center] += flt(row.amount_consumed);
    });

    if (Object.keys(grouped).length === 0) {
        frappe.msgprint(__('No fuel consumption data found.'));
        return;
    }

    const items = Object.keys(grouped).map(cost_center => ({
        item_code: "NS-00106",
        qty: 1,
        rate: grouped[cost_center],
        amount: grouped[cost_center],
        cost_center: cost_center,
        custom_fuel_consumption: frm.doc.name
    }));

    const to_date = frappe.datetime.str_to_obj(frm.doc.to_date);
    const monthName = to_date ? to_date.toLocaleString('default', { month: 'long' }) : '';
    const year = to_date ? to_date.getFullYear() : '';
    const balance = frm.doc.account_balance || 0;
    
    const remarks = `Fuel consumption for ${monthName} ${year} with account balance of BHD ${balance}.`;

    frappe.call({
        method: "frappe.client.insert",
        args: {
            doc: {
                doctype: "Purchase Invoice",
                supplier: "S0026",
                items: items,
                posting_date: frm.doc.reporting_date,
                set_posting_time: 1,
                remarks: remarks
            }
        },
        callback(r) {
            if (r.message) {
                frappe.msgprint(__('Purchase Invoice created: ') + r.message.name);
                frappe.set_route('Form', 'Purchase Invoice', r.message.name);

                frappe.show_alert({
                    message: __("Reminder: Please update the workflow state to 'Purchase Invoice Created' manually."),
                    indicator: 'yellow'
                });
            }
        }
    });
}