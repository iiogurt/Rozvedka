/* Find a connection: suggestions for both ends as one types (/api/entities/suggest) – actors by any of their
   names, list entries by label; the value carries the entity's id in brackets so the server knows which one. */
(function () {
  const list = document.getElementById("ent-list");
  if (!list) return;
  let timer = null, last = "";
  document.querySelectorAll("input[data-suggest]").forEach((input) => {
    input.addEventListener("input", () => {
      const q = input.value.trim();
      clearTimeout(timer);
      if (q.length < 2 || q === last || /\]\s*$/.test(q)) return;
      timer = setTimeout(() => {
        last = q;
        fetch("/api/entities/suggest?q=" + encodeURIComponent(q)).then((r) => r.json()).then((d) => {
          list.replaceChildren(...d.entities.map((e) => {
            const o = document.createElement("option");
            o.value = e.value;
            o.label = e.kind_name + " · " + e.links + " links";
            return o;
          }));
        }).catch(() => {});
      }, 200);
    });
  });
})();
