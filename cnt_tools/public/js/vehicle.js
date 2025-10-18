/*******************************************************
 * Doctype Script:     Vehicle
 * Maintained By:      Cloud Nine Technologies
 * Description:        Filters active employees,
 *                     auto-calculates NHRA certificate expiry,
 *                     controls edit access based on workflow state,
 *                     locks static fields after save
 * Version:            v1.6
 * Last Updated:       2025-10-16
 *******************************************************/

// ─────────────────────────────────────
// SECTION 1: MAIN DOCTYPE EVENTS (Vehicle)
// ─────────────────────────────────────
frappe.ui.form.on('Vehicle', {
    refresh(frm) {
        // Filter to show only active employees
        frm.set_query('employee', () => ({ filters: { status: 'Active' } }));

        // Apply workflow-based field access control
        toggle_field_access(frm);

        // ⚠️ Do NOT auto-set values on refresh; it dirties the form
        // (Expiry will be synced on change and before_save only)
    },

    workflow_state(frm) {
        toggle_field_access(frm);
    },

    // Keep auto sync when the user actually changes the issue date
    custom_nhra_cold_chain_certificate_issue_date(frm) {
        syncExpiryIfNeeded(frm);
    },

    before_save(frm) {
        // Ensure expiry is in sync at save time—without dirtying if already correct
        syncExpiryIfNeeded(frm);

        // Only add change-comments on updates (not new docs)
        if (frm.is_new()) return;

        frappe.call({
            method: "frappe.client.get",
            args: { doctype: frm.doc.doctype, name: frm.doc.name },
            callback(r) {
                if (!r.message) return;
                const old = r.message;
                const changed_fields = [];

                // 1) Assigned Employee
                if (old.employee !== frm.doc.employee) {
                    const old_employee = old.employee || 'Not Set';
                    const old_name     = old.custom_employee_name || 'Not Set';
                    const new_employee = frm.doc.employee || 'Not Set';
                    const new_name     = frm.doc.custom_employee_name || 'Not Set';
                    changed_fields.push(
                        `Assigned Employee changed from <a href="/app/employee/${old_employee}" target="_blank"><b>${old_employee}</b></a> (${old_name}) ` +
                        `to <a href="/app/employee/${new_employee}" target="_blank"><b>${new_employee}</b></a> (${new_name})`
                    );
                }

                // 2) Insurance company
                if (old.insurance_company !== frm.doc.insurance_company) {
                    changed_fields.push(
                        `Insurance company changed from <b>${old.insurance_company || 'Not Set'}</b> to <b>${frm.doc.insurance_company || 'Not Set'}</b>`
                    );
                }

                // 3) Policy number
                if (old.policy_no !== frm.doc.policy_no) {
                    changed_fields.push(
                        `Insurance policy number changed from <b>${old.policy_no || 'Not Set'}</b> to <b>${frm.doc.policy_no || 'Not Set'}</b>`
                    );
                }

                // 4) Insurance dates
                if (old.start_date !== frm.doc.start_date || old.end_date !== frm.doc.end_date) {
                    const start_date = frm.doc.start_date ? frappe.datetime.str_to_user(frm.doc.start_date) : 'Not Set';
                    const end_date   = frm.doc.end_date   ? frappe.datetime.str_to_user(frm.doc.end_date)   : 'Not Set';
                    changed_fields.push(`Insurance coverage period updated: from <b>${start_date}</b> to <b>${end_date}</b>`);
                }

                // 5) NHRA cold chain certificate (only when cold chain = Yes)
                if (frm.doc.custom_cold_chain === 'Yes') {
                    const ref_changed    = old.custom_nhra_cold_chain_certificate_reference !== frm.doc.custom_nhra_cold_chain_certificate_reference;
                    const issue_changed  = old.custom_nhra_cold_chain_certificate_issue_date !== frm.doc.custom_nhra_cold_chain_certificate_issue_date;
                    const expiry_changed = old.custom_nhra_cold_chain_certificate_expiry_date !== frm.doc.custom_nhra_cold_chain_certificate_expiry_date;

                    if (ref_changed || issue_changed || expiry_changed) {
                        const ref    = frm.doc.custom_nhra_cold_chain_certificate_reference || 'Not Set';
                        const issue  = frm.doc.custom_nhra_cold_chain_certificate_issue_date
                            ? frappe.datetime.str_to_user(frm.doc.custom_nhra_cold_chain_certificate_issue_date) : 'Not Set';
                        const expiry = frm.doc.custom_nhra_cold_chain_certificate_expiry_date
                            ? frappe.datetime.str_to_user(frm.doc.custom_nhra_cold_chain_certificate_expiry_date) : 'Not Set';
                        changed_fields.push(
                            `NHRA cold chain certificate updated: Ref <b>${ref}</b>, issued on <b>${issue}</b>, expiring on <b>${expiry}</b>`
                        );
                    }
                }

                // 6) Chassis / Engine newly added
                const chassis_added = !old.chassis_no && frm.doc.chassis_no;
                const engine_added  = !old.custom_engine_no && frm.doc.custom_engine_no;
                if (chassis_added || engine_added) {
                    changed_fields.push(
                        `Vehicle identification details added: Chassis No - <b>${frm.doc.chassis_no || 'Not Set'}</b>, ` +
                        `Engine No - <b>${frm.doc.custom_engine_no || 'Not Set'}</b>`
                    );
                }

                // 7) Registration expiry
                if (old.custom_registration_expiry_date !== frm.doc.custom_registration_expiry_date) {
                    const reg_expiry = frm.doc.custom_registration_expiry_date
                        ? frappe.datetime.str_to_user(frm.doc.custom_registration_expiry_date) : 'Not Set';
                    changed_fields.push(`Registration expiry date updated to <b>${reg_expiry}</b>`);
                }

                // Final comment
                if (changed_fields.length) {
                    const formattedDate = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
                    frappe.call({
                        method: "frappe.client.insert",
                        args: {
                            doc: {
                                doctype: "Comment",
                                comment_type: "Comment",
                                reference_doctype: frm.doc.doctype,
                                reference_name: frm.doc.name,
                                content: `Change made on <b>${formattedDate}:</b><br><br>` + changed_fields.join('<br>')
                            }
                        }
                    });
                }
            }
        });
    }
});

// ─────────────────────────────────────
// SECTION 2: HELPER FUNCTIONS
// ─────────────────────────────────────

/**
 * If Cold Chain = Yes and Issue Date set, ensure Expiry = Issue + 12 months.
 * Only sets the field when different, to avoid dirtying the form.
 */
function syncExpiryIfNeeded(frm) {
    // Only applicable when cold chain applies
    if (frm.doc.custom_cold_chain !== 'Yes') return;

    const issue = frm.doc.custom_nhra_cold_chain_certificate_issue_date || null;
    const currentExpiry = frm.doc.custom_nhra_cold_chain_certificate_expiry_date || null;

    let expectedExpiry = null;
    if (issue) {
        expectedExpiry = frappe.datetime.add_months(issue, 12);
    }

    // Normalize to yyyy-mm-dd for comparison (handles null as well)
    const norm = d => (d ? frappe.datetime.str_to_obj(d).toISOString().slice(0,10) : null);
    if (norm(currentExpiry) !== norm(expectedExpiry)) {
        frm.set_value('custom_nhra_cold_chain_certificate_expiry_date', expectedExpiry);
    }
}

/**
 * Controls field editability based on workflow state and document status
 */
function toggle_field_access(frm) {
    const is_new        = frm.doc.__islocal;
    const is_update     = frm.doc.workflow_state === 'Update in Progress';
    const is_editable   = is_new || is_update;

    const conditionally_editable_fields = [
        'employee',
        'insurance_company',
        'policy_no',
        'start_date',
        'end_date',
        'custom_insurance_premium',
        'custom_registration_expiry_date',
        'chassis_no',
        'custom_engine_no',
        'custom_nhra_cold_chain_certificate_reference',
        'custom_nhra_cold_chain_certificate_issue_date',
        'custom_license_number',
        'custom_license_number_expiry_date'
    ];

    conditionally_editable_fields.forEach(field => {
        frm.set_df_property(field, 'read_only', !is_editable);
        frm.refresh_field(field);
    });

    const static_fields = [
        'license_plate',
        'custom_model_year',
        'make',
        'model',
        'custom_type',
        'custom_cold_chain',
        'color'
    ];

    static_fields.forEach(field => {
        frm.set_df_property(field, 'read_only', is_new ? 0 : 1);
        frm.refresh_field(field);
    });
}