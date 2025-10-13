// Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
// For license information, please see license.txt

// apps/cnt_tools/cnt_tools/cnt_tools/doctype/bank_statement_run/bank_statement_run.js

function fmtCurrency(val, cur) {
	// Always render with 3 decimals, independent of system currency precision
	const num = (typeof val === 'number') ? val : (val != null && !isNaN(parseFloat(val)) ? parseFloat(val) : 0);
	const s = num.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
	const label = (cur === 'BHD') ? 'BD' : (cur || '');
	return label ? `${label} ${s}` : s;
  }
  
  function fmtNumber3(val) {
	const num = (typeof val === 'number') ? val : (val != null && !isNaN(parseFloat(val)) ? parseFloat(val) : 0);
	return num.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  }
  
  function stripHtml(html) {
	if (!html) return '';
	return String(html).replace(/<[^>]*>/g, '');
  }
  
  frappe.ui.form.on('Bank Statement Run', {
    
    // Auto-load mapping from the selected Bank Account (server method)
    async bank_account(frm) {
      if (!frm.doc.bank_account) return;
      try {
        const r = await frappe.call({
          method: 'cnt_tools.cnt_tools.doctype.bank_statement_run.bank_statement_run.get_mapping_for_bank_account',
          args: { bank_account: frm.doc.bank_account },
        });
        const map = r.message;
        if (map) {
          await frm.set_value(map);
          frappe.show_alert({ message: __('Statement mapping loaded from Bank Account.'), indicator: 'green' });
        }
      } catch (e) {
        console.error(e);
      }
    },

    refresh(frm) {
      if (frm.is_new()) return; // require saved doc before actions
      add_formatter_buttons(frm);
      enforce_import_lock(frm);
      // Actions → View Bank Transactions (only after an import attempt)
      if (!frm.is_new() && (frm.doc.status === 'Imported' || frm.doc.status === 'Failed')) {
        frm.add_custom_button(__('View Bank Transactions'), () => {
          const route_options = {};
          if (frm.doc.bank_account) {
            route_options.bank_account = frm.doc.bank_account;
          }
          if (frm.doc.statement_start && frm.doc.statement_end) {
            route_options.date = ['between', [frm.doc.statement_start, frm.doc.statement_end]];
          }
          if (frm.doc.currency) {
            route_options.currency = frm.doc.currency;
          }
          frappe.route_options = route_options;
          frappe.set_route('List', 'Bank Transaction');
        }, __('Actions'));
      }
    },

    after_save(frm) {
      add_formatter_buttons(frm);
      enforce_import_lock(frm);
      // Actions → View Bank Transactions (only after an import attempt)
      if (!frm.is_new() && (frm.doc.status === 'Imported' || frm.doc.status === 'Failed')) {
        frm.add_custom_button(__('View Bank Transactions'), () => {
          const route_options = {};
          if (frm.doc.bank_account) {
            route_options.bank_account = frm.doc.bank_account;
          }
          if (frm.doc.statement_start && frm.doc.statement_end) {
            route_options.date = ['between', [frm.doc.statement_start, frm.doc.statement_end]];
          }
          if (frm.doc.currency) {
            route_options.currency = frm.doc.currency;
          }
          frappe.route_options = route_options;
          frappe.set_route('List', 'Bank Transaction');
        }, __('Actions'));
      }
    },

    onload_post_render(frm) {
      enforce_import_lock(frm);
    },

  });
// Helper to toggle read-only for fields after import
function enforce_import_lock(frm) {
  const isImported = frm.doc && frm.doc.status === 'Imported';
  const fields_to_lock = [
    'bank_account',
    'statement_start',
    'statement_end',
    'source_file',
    'lock_mapping_fields',
  ];
  fields_to_lock.forEach(fn => {
    if (frm.get_field(fn)) {
      frm.set_df_property(fn, 'read_only', isImported ? 1 : 0);
    }
  });
  // Optional: also disable Save if imported (prevents accidental edits via API/UI)
  try {
    frm.toolbar && frm.toolbar.set_primary_action_visibility(!isImported);
  } catch(e) { /* ignore */ }
}
	
	function add_formatter_buttons(frm) {
	
	  // Single Preview Data button: re-parse and open dialog
  frm.add_custom_button(__('Preview Data'), async () => {
    if (!has_min_mapping(frm)) return;
    try {
      // frappe.dom.freeze(__('Parsing statement…'));
      await frm.call('preview_rows', { docname: frm.doc.name });
      await frm.reload_doc();
      show_preview_dialog(frm);
    } catch (e) {
      console.error('[Bank Statement Run] Preview Data failed', e);
      frappe.msgprint(__('Preview Data failed: {0}', [String(e && e.message || e)]));
    } finally {
      frappe.dom.unfreeze();
    }
  });
	
  // Only show Create Bank Transactions button after a successful parse
  if (frm.doc.status === 'Parsed') {
    frm.add_custom_button(__('Create Bank Transactions'), async () => {
      try {
        frappe.dom.freeze(__('Creating Bank Transactions…'));
        await frm.call('create_bank_transactions', { docname: frm.doc.name });
        frappe.show_alert({ message: __('Bank Transactions generated'), indicator: 'green' });
        // Immediately hide the button in the current UI state
        try {
          frm.clear_custom_buttons();
          // Optimistically reflect new status to avoid re-adding the button before reload
          frm.doc.status = 'Imported';
          frm.refresh_field('status');
          add_formatter_buttons(frm);
        } catch (uierr) { console.warn('Could not clear/rebuild buttons', uierr); }
        await frm.reload_doc();
      } catch (e) {
        console.error(e);
        // After failure the server sets status = Failed and failure_reason; reflect that
        try {
          await frm.reload_doc();
        } catch(_) {}
      } finally {
        frappe.dom.unfreeze();
      }
    }, __('Actions'));
  }
	}
	
	function has_min_mapping(frm) {
	  const d = frm.doc || {};
	  const missing = [];
	
	  if (!d.source_file) missing.push(__('Source File'));
	  if (!d.date_column) missing.push(__('Date Column'));
	  if (!d.description_column) missing.push(__('Description Column'));
	
	  if (d.has_credit_debit_columns) {
		if (!d.credit_column) missing.push(__('Credit Column'));
		if (!d.debit_column) missing.push(__('Debit Column'));
	  } else {
		if (!d.amount_column) missing.push(__('Amount Column'));
	  }
	
	  if (missing.length) {
		frappe.msgprint(__('Please fill: {0}', [missing.join(', ')]));
		return false;
	  }
	  return true;
	}
	
function show_preview_dialog(frm) {
  console.log('show_preview_dialog: start for', frm.doc && frm.doc.name);
  let payload = {};
  try {
    payload = frm.doc.preview_json ? JSON.parse(frm.doc.preview_json) : {};
  } catch (e) {
    console.error('[Bank Statement Run] Failed to parse preview_json', e);
    payload = {};
  }

  const sample = Array.isArray(payload.sample) ? payload.sample : [];

  let html = '';
  if (sample.length) {
    const cols = (Array.isArray(payload.columns) && payload.columns.length)
      ? payload.columns.map(c => (typeof c === 'string' ? c : (c.label || c.fieldname || c.name))).filter(Boolean)
      : Object.keys(sample[0]);
    html += '<div style="max-height:50vh; overflow:auto;">';
    html += '<table class="table table-bordered" style="margin-bottom:12px;">';
    html += '<thead><tr>' + cols.map(c => `<th>${frappe.utils.escape_html(c)}</th>`).join('') + '</tr></thead>';
    html += '<tbody>' + sample.map(row => {
      return '<tr>' + cols.map(c => {
        let v = row[c];
        if (c === 'Credit' || c === 'Debit') {
          const num = (v != null && !isNaN(parseFloat(v))) ? parseFloat(v) : 0;
          v = fmtNumber3(num);
        }
        return `<td>${frappe.utils.escape_html(v ?? '')}</td>`;
      }).join('') + '</tr>';
    }).join('') + '</tbody>';
    html += '</table>';
    html += '</div>';
  } else {
    html += '<p style="margin:0 0 8px 0;">' + __('No preview rows to display.') + '</p>';
  }

  try {
    const d = new frappe.ui.Dialog({
      title: __('Bank Statement Preview'),
      size: 'extra-large',
      primary_action_label: __('Close'),
      primary_action() { d.hide(); },
    });
    d.$body.html(html);
    d.show();
    console.log('[show_preview_dialog]: dialog displayed');
  } catch (e) {
    console.error('show_preview_dialog: dialog error', e);
    // Fallback: show in a msgprint so at least content is visible
    frappe.msgprint({
      title: __('Bank Statement Preview'),
      indicator: 'blue',
      message: `<div class="overflow-auto" style="max-height:50vh;">${html}</div>`,
      wide: true,
    });
  }
}