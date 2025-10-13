// Copyright (c) 2025, Cloud Nine Technologies (CNT) and contributors
// For license information, please see license.txt


// Robustly apply ListView filters after the list is fully rendered
function _apply_filters_when_ready(doctype, applyFn, attempts = 30) {
  const attempt = () => {
    if (cur_list && cur_list.doctype === doctype && cur_list.filter_area) {
      const f = cur_list.filter_area;
      try { f.clear_filters(); } catch (e) {}
      try { applyFn(f); } catch (e) { console && console.warn && console.warn('[Checkin Run] applyFn error', e); }
      try { f.apply(); } catch (e) {}
    } else if (attempts > 0) {
      setTimeout(() => attempt(), 150);
    }
  };
  setTimeout(() => attempt(), 0);
}

frappe.ui.form.on('Checkin Run', {
	refresh(frm) {
	  // Primary actions visible on form
	  add_parse_button(frm);
	  add_preview_button(frm);

	  // Actions group
	  add_generate_action(frm);

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
		  method: 'cnt_tools.cnt_tools.doctype.checkin_run.checkin_run.parse_source',
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
	  frm.add_custom_button(__('Preview Data'), () => {
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
		method: 'cnt_tools.cnt_tools.doctype.checkin_run.checkin_run.generate_checkins',
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
            `,
            indicator
          });
		  frm.reload_doc();
		}
	  });
	}, __('Actions'));
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
		method: 'cnt_tools.cnt_tools.doctype.checkin_run.checkin_run.cr_preview',
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

          // Add an "Open in List (filtered)" button that uses exact datetimes (with seconds)
          const footer = $(`
            <div class="mt-2">
              <button class="btn btn-sm btn-secondary cr-open-list">${__("Open in List (filtered)")}</button>
            </div>
          `);
          d.$body.append(footer);

          footer.find('.cr-open-list').on('click', async () => {
            // Prefer exact created window if already imported; else derive from preview rows
            let MIN = null, MAX = null;
            try {
              const status = (frm.doc.status || '').toLowerCase();
              if (status === 'imported') {
                const r2 = await frappe.call({
                  method: 'cnt_tools.cnt_tools.doctype.checkin_run.checkin_run.cr_imported_time_range',
                  args: { name: frm.doc.name },
                });
                const rng = (r2 && r2.message) || {};
                MIN = rng.min || null;
                MAX = rng.max || null;
              }
            } catch (e) { /* ignore */ }

            // Fallback to preview rows' min/max if not imported or missing
            if (!MIN || !MAX) {
              const times = (rows || []).map(r => r && r.event_time).filter(Boolean).sort();
              if (times.length) {
                MIN = MIN || times[0];
                MAX = MAX || times[times.length - 1];
              }
            }

            frappe.set_route('List', 'Employee Checkin');
            _apply_filters_when_ready('Employee Checkin', (f) => {
              const meta = frappe.get_meta('Employee Checkin');
              const has_backlink = !!(meta && meta.fields && meta.fields.some(df => df.fieldname === 'custom_checkin_run'));

              // Only filter by Checkin Run. No fallbacks.
              if (frm.doc.name && has_backlink) {
                f.add([[ 'Employee Checkin', 'custom_checkin_run', '=', frm.doc.name ]]);
              } else {
                // Force empty results when there is no backlink field or value
                f.add([[ 'Employee Checkin', 'name', '=', '__no_results__' ]]);
              }
            });
          });
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

// Removed add_results_buttons and show_results_modal functions and related event handler

frappe.ui.form.on('Checkin Run', {
  refresh(frm) {
    // Show after an import attempt to inspect what got created
    if (!frm.is_new() && (frm.doc.status === 'Imported' || frm.doc.status === 'Failed')) {
      frm.add_custom_button(__('View Employee Checkins'), () => {
        frappe.set_route('List', 'Employee Checkin');
        _apply_filters_when_ready('Employee Checkin', (f) => {
          const meta = frappe.get_meta('Employee Checkin');
          const has_backlink = !!(meta && meta.fields && meta.fields.some(df => df.fieldname === 'custom_checkin_run'));
          if (frm.doc.name && has_backlink) {
            f.add([[ 'Employee Checkin', 'custom_checkin_run', '=', frm.doc.name ]]);
          } else {
            f.add([[ 'Employee Checkin', 'name', '=', '__no_results__' ]]);
          }
        });
      }, __('Actions'));
    }
  },
  after_save(frm) {
    // Also add immediately after save so users don’t need to refresh
    if (!frm.is_new() && (frm.doc.status === 'Imported' || frm.doc.status === 'Failed')) {
      frm.add_custom_button(__('View Employee Checkins'), () => {
        frappe.set_route('List', 'Employee Checkin');
        _apply_filters_when_ready('Employee Checkin', (f) => {
          const meta = frappe.get_meta('Employee Checkin');
          const has_backlink = !!(meta && meta.fields && meta.fields.some(df => df.fieldname === 'custom_checkin_run'));
          if (frm.doc.name && has_backlink) {
            f.add([[ 'Employee Checkin', 'custom_checkin_run', '=', frm.doc.name ]]);
          } else {
            f.add([[ 'Employee Checkin', 'name', '=', '__no_results__' ]]);
          }
        });
      }, __('Actions'));
    }
  }
});