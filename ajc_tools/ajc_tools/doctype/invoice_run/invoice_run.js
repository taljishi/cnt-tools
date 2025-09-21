// Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
// For license information, please see license.txt

frappe.ui.form.on('Invoice Run', {
	refresh(frm) {
	  // Lock certain parent fields when Parsed/Imported
	  const lockParent = ['Parsed', 'Imported'].includes(frm.doc.status);
	  frm.toggle_enable(['supplier', 'duplicate_check_by'], !lockParent);
  
    // Show "Parse Data" in Draft OR when any child is Draft/Error
	  const hasDraftOrErrorChild = (frm.doc.source_files || []).some(r => ['Draft', 'Error'].includes(r.status));
	  if (frm.doc.status === 'Draft' || hasDraftOrErrorChild) {
      frm.add_custom_button(__('Parse Data'), async () => {
		  await frappe.call({
			method: 'ajc_tools.ajc_tools.doctype.invoice_run.invoice_run.parse_files',
			args: { name: frm.doc.name },
			freeze: true,
          freeze_message: __('Parsing source…')
		  });
		  frm.reload_doc();
      }).addClass('btn-primary');
	  }

      // Always offer View Import Log when there's anything to inspect (independent of Preview availability)
      const hasLog = (frm.doc.import_log || '').trim().length > 0;
      const hasParsed = frm.doc.status === 'Parsed' || (frm.doc.parsed_count || 0) > 0 || (frm.doc.ready_count || 0) > 0;
      const hasFailures = (frm.doc.failed_count || 0) > 0 || (frm.doc.skipped_count || 0) > 0 || (frm.doc.status === 'Failed');
      if (hasLog || hasParsed || hasFailures) {
        frm.add_custom_button(__('View Import Log'), () => {
          const d2 = new frappe.ui.Dialog({
            title: __('Import Log'),
            size: 'large',
            primary_action_label: __('Close'),
            primary_action() { d2.hide(); }
          });
          d2.$body.html(
            `<pre style="white-space: pre-wrap; font-family: var(--font-stack);">${frappe.utils.escape_html(frm.doc.import_log || __('No log yet.'))}</pre>`
          );
          d2.show();
        }, __('Actions'));
      }
  
	  // Show preview when there are ready rows or parent is Parsed
	  if ((frm.doc.ready_count || 0) > 0 || frm.doc.status === 'Parsed') {
		frm.add_custom_button(__('Preview'), async () => {
		  const r = await frappe.call({
			method: 'ajc_tools.ajc_tools.doctype.invoice_run.invoice_run.get_preview_html',
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __('Building preview…')
		  });
  
		  const d = new frappe.ui.Dialog({
			title: __('Purchase Invoices Preview'),
			size: 'extra-large',
			primary_action_label: __('Close'),
			primary_action: () => d.hide()
		  });
  
		  d.$body.html(r.message || '<div class="text-muted p-4">' + __('No preview available.') + '</div>');
		  d.show();
      });
	  
		// Separate action to generate PIs (under Actions)
		frm.add_custom_button(__('Create Purchase Invoices'), async () => {
		  await frappe.call({
			method: 'ajc_tools.ajc_tools.doctype.invoice_run.invoice_run.create_purchase_invoices',
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __('Creating Purchase Invoices…')
		  });
		  frm.reload_doc();
		}, __('Actions'));
	  }
  
	  // Hide the "clear" button on attached files for rows that are Parsed (visual safety)
	  try {
		(frm.doc.source_files || []).forEach((row, idx) => {
		  if (['Parsed'].includes(row.status)) {
			const grid = frm.fields_dict.source_files?.grid;
			const $row = grid?.grid_rows?.[idx]?.$row;
			$row && $row.find('.attached-file .btn-clear').hide();
		  }
		});
	  } catch (e) {
		// non-fatal UI tweak
	  }
	}
  });