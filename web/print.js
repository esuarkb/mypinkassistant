document.addEventListener('DOMContentLoaded', function () {
    var btnPrint = document.getElementById('btn-print');
    var searchBox = document.getElementById('inv-search');
    var currentView = 'all';

    // Accent-insensitive normalize so "limpiador" finds "Limpiador" on the ES catalog.
    function normText(s) {
        return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    // Precompute each row's searchable text (product name + SKU) once —
    // keeps per-keystroke filtering trivial across the full catalog.
    document.querySelectorAll('#inv-table tbody tr').forEach(function (row) {
        if (!row.dataset.sku) return; // skip the no-match placeholder row
        var name = row.cells[0] ? row.cells[0].textContent : '';
        row.dataset.search = normText(name + ' ' + row.dataset.sku);
    });

    btnPrint.addEventListener('click', function () {
        var checked = document.querySelector('input[name="view"]:checked');
        if (checked && checked.value === 'enter') {
            saveInventory();
        } else {
            window.focus();
            window.print();
        }
    });

    document.getElementById('view-all').addEventListener('change', function () {
        exitEnterMode();
        currentView = 'all';
        applyFilters();
    });

    document.getElementById('view-onhand').addEventListener('change', function () {
        exitEnterMode();
        currentView = 'onhand';
        applyFilters();
    });

    document.getElementById('view-enter').addEventListener('change', function () {
        currentView = 'all';
        applyFilters();
        toggleInputs(true);
        btnPrint.textContent = 'Save';
    });

    if (searchBox) {
        searchBox.addEventListener('input', applyFilters);
    }

    function updateGrandTotal() {
        var total = 0;
        document.querySelectorAll('#inv-table tbody tr').forEach(function (row) {
            if (row.classList.contains('hidden')) return;
            var val = parseFloat(row.dataset.retail || '0');
            if (val > 0) total += val;
        });
        var gtEl = document.getElementById('grand-total');
        if (gtEl) gtEl.textContent = '$' + total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    updateGrandTotal();

    function exitEnterMode() {
        toggleInputs(false);
        btnPrint.textContent = 'Print / Save PDF';
        btnPrint.disabled = false;
    }

    function toggleInputs(on) {
        document.querySelectorAll('.dv').forEach(function (el) {
            el.classList.toggle('hidden', on);
        });
        document.querySelectorAll('.ev').forEach(function (el) {
            el.classList.toggle('hidden', !on);
        });
    }

    function saveInventory() {
        var rows = document.querySelectorAll('#inv-table tbody tr');
        var payload = [];

        rows.forEach(function (row) {
            var sku = row.dataset.sku;
            if (!sku) return;

            var qtyInput = row.querySelector('.inv-input[data-field="qty"]');
            var parInput = row.querySelector('.inv-input[data-field="par"]');

            var qty = qtyInput && qtyInput.value.trim() !== '' ? parseInt(qtyInput.value, 10) : null;
            var par = parInput && parInput.value.trim() !== '' ? parseInt(parInput.value, 10) : null;

            if (qty !== null || par !== null) {
                payload.push({ sku: sku, qty: qty, par: par });
            }
        });

        btnPrint.disabled = true;
        btnPrint.textContent = 'Saving…';

        fetch('/inventory/bulk-save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok) {
                    window.location.reload();
                } else {
                    alert('Something went wrong saving. Please try again.');
                    btnPrint.disabled = false;
                    btnPrint.textContent = 'Save';
                }
            })
            .catch(function () {
                alert('Something went wrong saving. Please try again.');
                btnPrint.disabled = false;
                btnPrint.textContent = 'Save';
            });
    }

    // One combined predicate: a row shows only if it matches the current tab
    // AND the search text. Keeps search working identically on all three tabs
    // and surviving tab switches. Typed Enter-Inventory values live in the DOM,
    // so rows hidden by a search still save on Save.
    function applyFilters() {
        var q = searchBox ? normText(searchBox.value.trim()) : '';
        var anyVisible = false;
        document.querySelectorAll('#inv-table tbody tr').forEach(function (row) {
            if (!row.dataset.sku) return; // no-match placeholder handled below
            var hide = (currentView === 'onhand' && row.dataset.hasQty === '0') ||
                       (q !== '' && row.dataset.search.indexOf(q) === -1);
            row.classList.toggle('hidden', hide);
            if (!hide) anyVisible = true;
        });
        var noMatch = document.getElementById('no-match-row');
        if (noMatch) noMatch.classList.toggle('hidden', anyVisible);
        updateGrandTotal();
    }
});
