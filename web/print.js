document.addEventListener('DOMContentLoaded', function () {
    var btnPrint = document.getElementById('btn-print');

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
        filterRows('all');
    });

    document.getElementById('view-onhand').addEventListener('change', function () {
        exitEnterMode();
        filterRows('onhand');
    });

    document.getElementById('view-enter').addEventListener('change', function () {
        filterRows('all');
        toggleInputs(true);
        btnPrint.textContent = 'Save';
    });

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

    function filterRows(view) {
        document.querySelectorAll('#inv-table tbody tr').forEach(function (row) {
            if (view === 'onhand') {
                row.classList.toggle('hidden', row.dataset.hasQty === '0');
            } else {
                row.classList.remove('hidden');
            }
        });
    }
});
