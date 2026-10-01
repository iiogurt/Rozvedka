// Some agencies publish their logo in white for a dark site header; on the white logo tiles it vanishes.
// Same-origin logos (/logo/<id>) are sampled on a canvas: white artwork on a transparent background gets a dark tile.
(function () {
  const N = 64;

  function isLightOnTransparent(img) {
    const c = document.createElement("canvas");
    c.width = c.height = N;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, N, N);
    const px = ctx.getImageData(0, 0, N, N).data;
    // how far the visible pixels stand out from a white tile (0 = invisible, 255 = black), weighted by opacity
    let alpha = 0, contrast = 0;
    for (let i = 0; i < px.length; i += 4) {
      const a = px[i + 3] / 255;
      alpha += a;
      contrast += a * (255 - (0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]));
    }
    // white artwork scores ~0–55 (DIA's red "250" anniversary mark is the highest); logos that fill most of the canvas
    // (Luxembourg's lion on a white plate, white JPGs with dark text) keep the white tile
    return alpha > 0 && alpha < N * N * 0.6 && contrast / alpha < 55;
  }

  function check(img) {
    if (!img.src.includes("/logo/") || img.dataset.lumChecked) return;
    img.dataset.lumChecked = "1";
    try {
      if (isLightOnTransparent(img)) {
        img.classList.add("logo-light");
        if (img.parentElement?.classList.contains("logo")) img.parentElement.classList.add("has-logo-light");
      }
    } catch (e) { /* undecodable image: leave the tile as it is */ }
  }

  // load does not bubble, but it can be captured – this also covers logos added later (map hover cards, popups)
  document.addEventListener("load", (e) => { if (e.target.tagName === "IMG") check(e.target); }, true);
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('img[src*="/logo/"]').forEach((img) => { if (img.complete && img.naturalWidth) check(img); });
  });
})();
