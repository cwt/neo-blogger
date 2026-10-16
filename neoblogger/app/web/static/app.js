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

// Post-upload success-banner Copy button (spec §10.1): the /upload view
// flashes "Uploaded: /images/<id>.webp" and redirects; enhance that banner
// with a one-click copy control carrying the same data-copy-url contract.
document.querySelectorAll(".flash-success").forEach((banner) => {
  const match = banner.textContent.match(/\/images\/[0-9a-f]{24}\.webp/);
  if (!match || banner.querySelector("[data-copy-url]")) return;
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.copyUrl = match[0];
  button.textContent = "Copy URL";
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(match[0]);
    const original = button.textContent;
    button.textContent = "Copied!";
    window.setTimeout(() => {
      button.textContent = original;
    }, 1500);
  });
  banner.appendChild(button);
});

// Delete confirmation via the shared <dialog> (spec §4.5, §5.4, §6, §7).
// Progressive enhancement: without JS the delete forms submit immediately.
const confirmDialog = document.getElementById("confirm-dialog");
const confirmMessage = document.getElementById("confirm-dialog-message");
const confirmCancel = document.getElementById("confirm-dialog-cancel");
const confirmOk = document.getElementById("confirm-dialog-confirm");
let pendingDeleteForm = null;
if (confirmDialog && typeof confirmDialog.showModal === "function") {
  document.querySelectorAll('form[action*="/delete"]').forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "true") return;
      event.preventDefault();
      pendingDeleteForm = form;
      if (confirmMessage) {
        confirmMessage.textContent = "Are you sure you want to delete this?";
      }
      confirmDialog.showModal();
    });
  });
  if (confirmCancel) {
    confirmCancel.addEventListener("click", () => {
      pendingDeleteForm = null;
      confirmDialog.close();
    });
  }
  if (confirmOk) {
    confirmOk.addEventListener("click", () => {
      const target = pendingDeleteForm;
      pendingDeleteForm = null;
      if (target) {
        target.dataset.confirmed = "true";
        target.submit();
      }
    });
  }
}

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

  const editor = new EasyMDE({
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
  // Keep the replaced textarea in sync: it stays `required` while hidden,
  // and browsers refuse to submit a form with an empty required control —
  // without this, Publish silently does nothing (spec §5.1).
  editor.codemirror.on("change", () => {
    editor.codemirror.save();
  });
}

// Cover picker on the editor page (spec §5.1): choosing an uploaded
// image fills the cover field. Without JS the URLs printed under each
// thumbnail are copied by hand.
const coverField = document.getElementById("cover_url");
if (coverField) {
  const pickerButtons = document.querySelectorAll("[data-cover-url]");
  pickerButtons.forEach((control) => {
    control.addEventListener("click", () => {
      coverField.value = control.dataset.coverUrl || "";
      coverField.focus();
      pickerButtons.forEach((other) => {
        other.setAttribute("aria-pressed", other === control ? "true" : "false");
      });
    });
  });
}

// Lightweight comment toolbar (spec §6): bold, italic, link, code, preview.
const commentField = document.getElementById("comment-text");
if (commentField && typeof EasyMDE !== "undefined") {
  const commentEditor = new EasyMDE({
    element: commentField,
    spellChecker: false,
    autoDownloadFontAwesome: false,
    autosave: { enabled: false },
    toolbar: ["bold", "italic", "link", "code", "preview"],
  });
  commentEditor.codemirror.on("change", () => {
    commentEditor.codemirror.save();
  });
}

// Navigation menu (mobile dropdown): close after choosing an entry or
// tapping outside the panel, so the next page never opens with it stuck.
const navToggle = document.querySelector('.site-header details.nav-menu');
const navLinks = document.querySelector('.site-header ul.nav-links');
if (navToggle && navLinks) {
  navLinks.addEventListener('click', (event) => {
    if (event.target.closest('a, button')) {
      navToggle.open = false;
    }
  });
  document.addEventListener('click', (event) => {
    if (navToggle.open && !event.target.closest('.site-header nav')) {
      navToggle.open = false;
    }
  });
}
