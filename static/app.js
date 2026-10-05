// The server repeats this validation. JavaScript only makes the form easier to use.
const data = document.getElementById('category-kinds');
const kind = document.getElementById('id_kind');
const category = document.getElementById('id_category');
if (data && kind && category) {
  const kinds = new Map(JSON.parse(data.textContent).map(item => [String(item.id), item.kind]));
  function filterCategories() {
    for (const option of category.options) {
      const unavailable = option.value && kinds.get(option.value) !== kind.value;
      option.hidden = Boolean(unavailable);
      option.disabled = Boolean(unavailable);
    }
    if (category.selectedOptions[0]?.disabled) category.value = '';
  }
  kind.addEventListener('change', filterCategories);
  filterCategories();
}
