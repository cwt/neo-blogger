/* Neo-Blogger client behaviors: progressive enhancement only. */

// Back-to-top button (§17): appears after scrolling.
const topButton = document.getElementById("back-to-top");
if (topButton) {
  window.addEventListener("scroll", () => {
    topButton.hidden = window.scrollY < 300;
  });
  topButton.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

// Copy affordance on each highlighted code block (spec §6).
document.querySelectorAll("div.highlight").forEach((block) => {
  const pre = block.querySelector("pre");
  if (!pre) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button";
  button.setAttribute("aria-label", "Copy code to clipboard");
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(pre.innerText);
    button.textContent = "Copied!";
    window.setTimeout(() => {
      button.textContent = "Copy";
    }, 1500);
  });
  block.appendChild(button);
});

// One-click clipboard copy with visual feedback (spec §10.1).
document.querySelectorAll("[data-copy-url]").forEach((control) => {
  control.addEventListener("click", async () => {
    await navigator.clipboard.writeText(control.dataset.copyUrl);
    const original = control.textContent;
    control.textContent = "Copied!";
    window.setTimeout(() => {
      control.textContent = original;
    }, 1500);
  });
});

// EasyMDE article editor with the editor-toolbar image button (spec §5.1).
const bodyField = document.getElementById("body");
if (bodyField && typeof EasyMDE !== "undefined") {
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? csrfMeta.content : "";

  async function uploadEditorImage(file) {
    const form = new FormData();
    form.append("image", file);
    const response = await fetch("/upload/editor", {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken },
      body: form,
    });
    if (!response.ok) {
      throw new Error("upload failed");
    }
    return (await response.json()).url;
  }

  function imageAction(editor) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".jpg,.jpeg,.png,.webp,.gif";
    input.onchange = () => {
      const file = input.files && input.files[0];
      if (!file) return;
      uploadEditorImage(file)
        .then((url) => {
          editor.codemirror.replaceSelection(`![](${url})`);
        })
        .catch(() => {
          editor.codemirror.replaceSelection("Upload failed.");
        });
    };
    input.click();
  }

  new EasyMDE({
    element: bodyField,
    spellChecker: false,
    autoDownloadFontAwesome: false,
    autosave: { enabled: false },
    toolbar: [
      "bold", "italic", "heading", "|",
      "quote", "unordered-list", "ordered-list", "table", "|",
      {
        name: "insert-image",
        action: imageAction,
        className: "fa fa-image",
        title: "Insert image (uploads)",
      },
      "|",
      "preview", "side-by-side", "|",
      "guide",
    ],
  });
} else if (bodyField) {
  // Progressive enhancement fallback: the plain textarea still works.
}
