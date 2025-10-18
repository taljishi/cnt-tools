/*******************************************************
 * Doctype Script:     Fuel Card
 * Maintained By:      Cloud Nine Technologies
 * Description:        Workflow-based field logic, auto-fetch, and tracking
 * Version:            v3.1
 * Last Updated:       2025-05-20
 *******************************************************/

// ─────────────────────────────────────────
// SECTION 1: MAIN DOCTYPE EVENTS
// ─────────────────────────────────────────
frappe.ui.form.on('Fuel Card', {
    refresh(frm) {
        toggle_field_access(frm);

        frm.set_query('vehicle', () => ({ filters: { workflow_state: 'In Use' } }));
        frm.set_query('employee', () => ({ filters: { status: 'Active' } }));

        check_and_update_expired(frm);
    },

    workflow_state(frm) {
        toggle_field_access(frm);
    },

    card_assignment_type(frm) {
        toggle_field_access(frm);
    
        const is_new = frm.doc.__islocal;
        const is_update = frm.doc.workflow_state === 'Update in Progress';
    
        if ((is_new && frm.doc.__unsaved) || is_update) {
            ['vehicle', 'employee', 'department', 'license_plate', 'make', 'model'].forEach(f => frm.set_value(f, null));
        }
    },

    vehicle(frm) {
        if (frm.doc.card_assignment_type === 'Vehicle Locked' && frm.doc.vehicle) {
            frappe.db.get_value('Vehicle', frm.doc.vehicle, 'custom_driver').then(r => {
                if (r.message?.custom_driver) {
                    frm.set_value('employee', r.message.custom_driver);
                }
            });
        }
        toggle_field_access(frm);
    },

    employee(frm) {
        if (frm.doc.employee) {
            frappe.db.get_value('Employee', frm.doc.employee, 'department').then(r => {
                if (r.message?.department) {
                    frm.set_value('department', r.message.department);
                }
            });
        } else {
            frm.set_value('department', null);
        }
    },

    before_save(frm) {
        log_assignment_changes(frm);
    }
});

// ─────────────────────────────────────────
// SECTION 2: EXPIRED CARD CHECK
// ─────────────────────────────────────────
function check_and_update_expired(frm) {
    const expiry = frm.doc.fuel_card_expiry_date;
    const today = frappe.datetime.get_today();

    if (["Cancelled", "Expired"].includes(frm.doc.workflow_state)) return;

    if (expiry && expiry < today) {
        frappe.call({
            method: 'frappe.client.set_value',
            args: {
                doctype: 'Fuel Card',
                name: frm.doc.name,
                fieldname: 'workflow_state',
                value: 'Expired'
            },
            callback: () => {
                const formattedDate = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
                frappe.call({
                    method: 'frappe.client.insert',
                    args: {
                        doc: {
                            doctype: 'Comment',
                            comment_type: 'Comment',
                            reference_doctype: frm.doctype,
                            reference_name: frm.doc.name,
                            content: `Card marked as <b>Expired</b> on ${formattedDate}`
                        }
                    }
                });
                frappe.msgprint(__('Card status has been set to <b>Expired</b>'));
                frm.reload_doc();
            }
        });
    }
}

// ─────────────────────────────────────────
// SECTION 3: FIELD ACCESS CONTROL
// ─────────────────────────────────────────
function toggle_field_access(frm) {
    const is_new = frm.doc.__islocal;
    const is_update = frm.doc.workflow_state === 'Update in Progress' || is_new;
    const assignment = frm.doc.card_assignment_type;
    const is_cancelled = frm.doc.workflow_state === 'Cancelled';

    const is_vehicle_locked = assignment === 'Vehicle Locked';
    const is_employee_assigned = assignment === 'Employee Assigned';
    const is_shared_use = assignment === 'Shared Use';

    const lock_all_fields = [
        'vehicle', 'employee', 'department',
        'license_plate', 'make', 'model',
        'monthly_fuel_budget', 'fuel_card_expiry_date',
        'card_assignment_type'
    ];

    if (is_cancelled) {
        lock_all_fields.forEach(f => {
            frm.set_df_property(f, 'read_only', 1);
            frm.set_df_property(f, 'hidden', 0);
            frm.set_df_property(f, 'reqd', false);
        });
        frm.refresh_fields();
        return;
    }

    // ─── Vehicle ───
    frm.set_df_property('vehicle', 'hidden', !is_vehicle_locked);
    frm.set_df_property('vehicle', 'read_only', !is_new && is_vehicle_locked);
    frm.set_df_property('vehicle', 'reqd', is_vehicle_locked && is_new);

    // ─── Employee ───
    frm.set_df_property('employee', 'hidden', is_shared_use);
    const lock_employee = (is_vehicle_locked && frm.doc.workflow_state !== 'Update in Progress') || is_cancelled;
    const lock_employee_due_to_assignment = (
        (is_vehicle_locked && !is_update) ||
        (is_employee_assigned && !is_update)
    );
    
    frm.set_df_property('employee', 'read_only', lock_employee_due_to_assignment || is_cancelled);
    frm.set_df_property('employee', 'reqd', is_employee_assigned && (is_new || is_update));

    if (is_vehicle_locked && frm.doc.vehicle) {
        frappe.db.get_value('Vehicle', frm.doc.vehicle, 'employee').then(r => {
            const assigned_employee = r.message?.employee;
            frm.set_query('employee', () => ({ filters: { name: assigned_employee } }));
        });
    } else {
        frm.set_query('employee', () => ({ filters: { status: 'Active' } }));
    }

    // ─── Department ───
    if (is_shared_use) {
        frm.set_df_property('department', 'hidden', false);
        frm.set_df_property('department', 'read_only', !is_update);
        frm.set_df_property('department', is_new || is_update);

        if (is_new && !frm.doc.department) {
            frm.set_value('department', 'General Services - AJC');
        }
    } else {
        frm.set_df_property('department', 'hidden', false);
        frm.set_df_property('department', 'read_only', true);
        frm.set_df_property('department', 'reqd', false);
    }

    // ─── Monthly Fuel Budget ───
    frm.set_df_property('monthly_fuel_budget', 'read_only', !is_update);

    // ─── Card Expiry ───
    frm.set_df_property('fuel_card_expiry_date', 'read_only', !is_new);

    // ─── Assignment Type ───
    const assignment_locked =
        (!is_new && frm.doc.card_assignment_type === 'Vehicle Locked') ||
        (!is_new && frm.doc.workflow_state !== 'Update in Progress');
    frm.set_df_property('card_assignment_type', 'read_only', assignment_locked);

    const all_options = ['Vehicle Locked', 'Employee Assigned', 'Shared Use'];
    const editable_options = ['Employee Assigned', 'Shared Use'];

    if (assignment_locked) {
        frm.set_df_property('card_assignment_type', 'options', all_options.join('\n'));
    } else if (is_new) {
        frm.set_df_property('card_assignment_type', 'options', all_options.join('\n'));
    } else {
        frm.set_df_property('card_assignment_type', 'options', editable_options.join('\n'));
    }

    frm.refresh_fields();
}

// ─────────────────────────────────────────
// SECTION 4: COMMENT LOGGING
// ─────────────────────────────────────────
function log_assignment_changes(frm) {
    const previous_doc = frm.get_docinfo()?.__docs_before_save?.find(d => d.name === frm.doc.name);
    const old_employee = previous_doc?.employee ?? null;
    const old_budget = parseFloat(previous_doc?.monthly_fuel_budget ?? 0);

    const new_employee = frm.doc.employee ?? null;
    const new_employee_name = frm.doc.employee_name ?? null;
    const new_budget = parseFloat(frm.doc.monthly_fuel_budget ?? 0);

    const changes = [];

    if (old_employee && old_employee !== new_employee && new_employee) {
        const empLink = `<a href="/app/employee/${new_employee}" target="_blank"><b>${new_employee}</b></a>`;
        const empName = new_employee_name ? ` (${new_employee_name})` : '';
        changes.push(`Assigned employee updated to ${empLink}${empName}`);
    }

    if (old_budget !== new_budget) {
        changes.push(`Monthly fuel budget updated to <b>BD ${new_budget}</b>`);
    }

    if (changes.length > 0) {
        const formattedDate = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
        const message = `Change made on ${formattedDate}:<br>${changes.join('<br>')}`;

        frappe.call({
            method: 'frappe.client.insert',
            args: {
                doc: {
                    doctype: 'Comment',
                    comment_type: 'Comment',
                    reference_doctype: frm.doctype,
                    reference_name: frm.doc.name,
                    content: message
                }
            }
        });
    }
}