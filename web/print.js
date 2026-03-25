document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('btn-print').addEventListener('click', function () {
        window.focus();
        window.print();
    });

    document.getElementById('view-all').addEventListener('change', function () {
        filterRows('all');
    });

    document.getElementById('view-onhand').addEventListener('change', function () {
        filterRows('onhand');
    });

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
