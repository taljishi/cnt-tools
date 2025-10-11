// Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
// For license information, please see license.txt

// /home/frappe/bench-v14/apps/ajc_tools/ajc_tools/doctype/checkin_run/checkin_run.js

frappe.ui.form.on('Checkin Run', {
	refresh(frm) {
	  // Primary actions visible on form
	  add_parse_button(frm);
	  add_preview_button(frm);

	  // Actions group
	  add_generate_action(frm);

	  // Results / Reasons quick access
	  add_results_buttons(frm);
  
	  // Lock fields/child rows as needed based on status
	  enforce_locks(frm);
	}
  });
	
frappe.ui.form.on('Checkin Source File', {
  form_render(frm, cdt, cdn) {
    // Re-apply locks when a child row is opened/edited
    if (frm && frm.doc && frm.doc.doctype === 'Checkin Run') {
      enforce_locks(frm);
    }
  }
});

	function add_parse_button(frm) {
	  const status = (frm.doc.status || '').toLowerCase();
	  if (status === 'imported' || status === 'parsed') {
		return; // hide Parse Data after parsing or generation
	  }
	
	  frm.add_custom_button(__('Parse Data'), () => {
		if (!frm.doc.source_files || !frm.doc.source_files.length) {
		  frappe.msgprint(__('Add at least one source file (in the Source Files table) before parsing.'));
		  return;
		}
	
		frappe.call({
		  method: 'ajc_tools.ajc_tools.doctype.checkin_run.checkin_run.parse_source',
		  args: { name: frm.doc.name, show_popup: 1 },
		  freeze: true,
		  callback: () => {
			// Server shows its own summary popup; just refresh counts/status.
			frm.reload_doc();
		  }
		});
	  }).addClass('btn-primary');
	}
	
	function add_preview_button(frm) {
	  frm.add_custom_button(__('Preview'), () => {
		if (!frm.doc.source_files || !frm.doc.source_files.length) {
		  frappe.msgprint(__('Add at least one source file (in the Source Files table) before previewing.'));
		  return;
		}
		open_preview_dialog(frm);
	  });
	}
	
  function add_generate_action(frm) {
	const status = (frm.doc.status || '').toLowerCase();
	if (status !== 'parsed') {
	  return; // show Create Employee Checkins ONLY when status is Parsed
	}
  
	frm.add_custom_button(__('Create Employee Checkins'), () => {
	  frappe.call({
		method: 'ajc_tools.ajc_tools.doctype.checkin_run.checkin_run.generate_checkins',
		args: { name: frm.doc.name },
		freeze: true,
		callback: (r) => {
		  const d = r.message || {};
          const counts = {
            created: d.created || 0,
            already_exists: d.already_exists || 0,
            failed: d.failed || 0
          };
          const indicator = counts.failed ? 'red' : (counts.created ? 'green' : 'orange');

          frappe.msgprint({
            title: __('Employee Checkins Import'),
            message: `
              <div><b>${__('Imported')}:</b> ${counts.created}</div>
              <div><b>${__('Skipped (already existed)')}:</b> ${counts.already_exists}</div>
              <div><b>${__('Failed')}:</b> ${counts.failed}</div>
              <hr/>
              <div>${__('Last Checkin Time')}: <b>${frappe.datetime.str_to_user(d.last_checkin_time || '') || '-'}</b></div>
              <div>${__('Shift Types Updated')}: <b>${d.shifts_updated || 0}</b></div>
              <div class="mt-3">
                <a class="btn btn-sm btn-default" onclick="cur_frm && cur_frm.script_manager && cur_frm.script_manager.trigger ? cur_frm.script_manager.trigger('show_results_modal') : null">${__('View Logs')}</a>
              </div>
            `,
            indicator
          });
		  frm.reload_doc();
		}
	  });
	}, __('Actions'));
  }
	
	function add_results_buttons(frm) {
  if (!frm.doc || !frm.doc.result_json) return;
  frm.add_custom_button(__('View Import Log'), () => {
    show_results_modal(frm);
  }, __('Actions'));
}

function show_results_modal(frm) {
  let data = [];
  try { data = JSON.parse(frm.doc.result_json || "[]"); } catch (e) {}
  const rows = data.slice(0, 300);
  const d = new frappe.ui.Dialog({
    title: __('Import Log'),
    size: 'extra-large',
    primary_action_label: __('Close'),
    primary_action() { d.hide(); }
  });

  const table = `
    <div style="max-height:60vh; overflow:auto;">
      <table class="table table-bordered table-compact small">
        <thead>
          <tr>
            <th>#</th>
            <th>${__('Time')}</th>
            <th>${__('UID')}</th>
            <th>${__('Employee')}</th>
            <th>${__('Status')}</th>
            <th>${__('Detail')}</th>
            <th>${__('Name')}</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((r, i) => `
            <tr>
              <td>${i + 1}</td>
              <td>${frappe.utils.escape_html(r.time || '')}</td>
              <td>${frappe.utils.escape_html(r.uid || '')}</td>
              <td>${frappe.utils.escape_html(r.employee || '')}</td>
              <td>${frappe.utils.escape_html(r.status || '')}</td>
              <td>${frappe.utils.escape_html(r.detail || '')}</td>
              <td>${frappe.utils.escape_html(r.name || '')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="mt-2 text-muted">${__('Full list is stored on this document (Result JSONn).')}</div>
  `;

  d.$body.html(table);
  d.show();
}

	function open_preview_dialog(frm) {
	  const d = new frappe.ui.Dialog({
		title: __('Device Events Overview'),
		size: 'extra-large',
		primary_action_label: __('Close'),
		primary_action() { d.hide(); }
	  });
	
	  d.$body.html(`
		<div class="cr-preview-summary"></div>
		<div class="cr-preview-table" style="max-height:60vh; overflow:auto; border:1px solid var(--border-color);"></div>
	  `);
	
	  d.show();
	
	  // Fetch first page
	  frappe.call({
		method: 'ajc_tools.ajc_tools.doctype.checkin_run.checkin_run.cr_preview',
		args: { name: frm.doc.name, start: 0, page_len: 200, order: 'desc' },
		callback: (r) => {
		  const res = r.message || {};
		  const total = res.total || 0;
		  const ready = res.ready || 0;
		  const rows = res.rows || [];
	
		  d.$body.find('.cr-preview-summary').html(`
			<div class="mb-2">
			  ${__('Rows')}: <b>${total}</b> &nbsp; | &nbsp; ${__('Ready')}: <b>${ready}</b>
			</div>
		  `);
	
		  if (!rows.length) {
			d.$body.find('.cr-preview-table').html(`<div class="text-muted">${__('No rows to display.')}</div>`);
			return;
		  }
	
		  const headers = ['#', __('Event Time'), __('Employee'), __('Attendance Device ID'), __('Device Name'), __('Source File'), __('Ready')];
		  const thead = `<thead><tr>${headers.map(h => `<th style="white-space:nowrap;">${h}</th>`).join('')}</tr></thead>`;
		  const tbody = `<tbody>
			${rows.map(r => `
			  <tr>
				<td>${frappe.utils.escape_html(r.idx || '')}</td>
				<td>${frappe.utils.escape_html(r.event_time || '')}</td>
				<td>${frappe.utils.escape_html(r.employee || '')}</td>
				<td>${frappe.utils.escape_html(r.attendance_device_id || '')}</td>
				<td>${frappe.utils.escape_html(r.device_name || '')}</td>
				<td>${frappe.utils.escape_html(r.source_file || '')}</td>
				<td>${(r.ready ? __('✅') : __('❌'))}</td>
			  </tr>`).join('')}
		  </tbody>`;
	
		  d.$body.find('.cr-preview-table').html(`
			<table class="table table-bordered table-compact small">
			  ${thead}
			  ${tbody}
			</table>
		  `);
		}
	  });
	}
  
  function enforce_locks(frm) {
  // Reusable selector list for file controls we want to disable when frozen
  const clearSelectors = [
    '[data-fieldname="file"] .attached-file .btn',
    '[data-fieldname="file"] .btn-attach-clear',
    '[data-fieldname="file"] .clear-attach',
    '[data-fieldname="file"] .remove-link',
    '[data-fieldname="file"] .close'
  ].join(',');

	const status = (frm.doc.status || '').toLowerCase();
	const frozen = (status === 'imported');
  
	// Parent fields read-only when imported
	try {
	  frm.set_df_property('cutoff_time', 'read_only', frozen ? 1 : 0);
	  frm.set_df_property('log_window_seconds', 'read_only', frozen ? 1 : 0);
	} catch (e) { /* ignore */ }
  
	// Child table controls
	const tbl = frm.get_field('source_files');
	if (!tbl || !tbl.grid) return;
	const grid = tbl.grid;
  
	// Prevent adding/removing rows when imported
	grid.cannot_add_rows = frozen;
	grid.cannot_delete_rows = frozen;
  
	// Toggle UI buttons for add/remove
	try {
	  grid.wrapper.find('.grid-add-row').toggle(!frozen);
	  grid.wrapper.find('.grid-remove-rows').toggle(!frozen);
	} catch (e) { /* ignore */ }
  
	// Make file column read-only when imported (others are already read-only per your DocType)
	try {
	  grid.update_docfield_property('file', 'read_only', frozen ? 1 : 0);

	  // Hide/disable file clear/remove controls when frozen (prevent accidental detach)
	  try {
		grid.wrapper.find(clearSelectors).toggle(!frozen);

		// Block clicks on any residual clear/remove buttons while frozen
		if (frozen) {
		  grid.wrapper.off('click.cr_lock');
		  grid.wrapper.on('click.cr_lock', clearSelectors, function (e) {
			e.preventDefault();
			e.stopImmediatePropagation();
			return false;
		  });
		} else {
		  // Unbind when unfrozen so normal behavior returns
		  grid.wrapper.off('click.cr_lock');
		}
	  } catch (e) { /* ignore */ }
	} catch (e) { /* ignore */ }

  // Re-enforce after focus/click on file field which can re-create clear buttons
  try {
    grid.wrapper.off('click.cr_lock_dynamic');
    grid.wrapper.on('click.cr_lock_dynamic', '[data-fieldname="file"]', function () {
      setTimeout(() => {
        try {
          grid.wrapper.find(clearSelectors).toggle(!frozen);
        } catch (e) { /* ignore */ }
      }, 0);
    });
  } catch (e) { /* ignore */ }

  // Also re-apply shortly after refresh to catch async grid re-renders
  setTimeout(() => {
    try {
      grid.wrapper.find(clearSelectors).toggle(!frozen);
    } catch (e) { /* ignore */ }
  }, 100);
  }

// Allow the inline "View Logs" link to trigger the modal
frappe.ui.form.on('Checkin Run', {
  show_results_modal: function(frm) {
    show_results_modal(frm);
  }
});