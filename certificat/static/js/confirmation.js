/**
 * Standard confirmation messages for various actions.
 * This file should be included in templates that need confirmation dialogs.
 */

// Standard confirmation messages
const STANDARD_CONFIRMATIONS = {
  DELETE_DOCUMENT: "Sigur doriți să ștergeți acest document?",
  DELETE_USER: "Sigur doriți să ștergeți acest utilizator?",
  DELETE_GESTIUNE: "Sigur doriți să ștergeți această gestiune?",
  DELETE_TIPOLOGIE: "Sigur doriți să ștergeți această tipologie?",
  DELETE_RANGE: "Sigur doriți să ștergeți această plajă de numere?",
  GENERATE_DOCUMENT: "Ești sigur că vrei să generezi documentul final? Această acțiune nu poate fi anulată.",
  EMPTY_FIELDS: "Există câmpuri necompletate. Doriți să continuați?",
  UNSAVED_CHANGES: "Aveți modificări nesalvate. Doriți să părăsiți pagina?"
};

/**
 * Applies standard confirmation to delete links/buttons
 * @param {string} selector - CSS selector for delete buttons
 * @param {string} messageKey - Key from STANDARD_CONFIRMATIONS
 */
function applyDeleteConfirmation(selector, messageKey) {
  const buttons = document.querySelectorAll(selector);
  const message = STANDARD_CONFIRMATIONS[messageKey] || STANDARD_CONFIRMATIONS.DELETE_DOCUMENT;

  buttons.forEach(button => {
    // Remove any existing onclick handler and set our standardized one
    button.removeAttribute('onclick');
    button.addEventListener('click', function(e) {
      if (!confirm(message)) {
        e.preventDefault();
        return false;
      }
      return true;
    });
  });
}

// Call this when DOM is ready to apply confirmations
document.addEventListener('DOMContentLoaded', function() {
  // Apply specific confirmation dialogs based on the page
  if (document.querySelector('.delete-document-btn')) {
    applyDeleteConfirmation('.delete-document-btn', 'DELETE_DOCUMENT');
  }

  if (document.querySelector('.delete-user-btn')) {
    applyDeleteConfirmation('.delete-user-btn', 'DELETE_USER');
  }

  if (document.querySelector('.delete-gestiune-btn')) {
    applyDeleteConfirmation('.delete-gestiune-btn', 'DELETE_GESTIUNE');
  }

  if (document.querySelector('.delete-tipologie-btn')) {
    applyDeleteConfirmation('.delete-tipologie-btn', 'DELETE_TIPOLOGIE');
  }

  if (document.querySelector('.delete-range-btn')) {
    applyDeleteConfirmation('.delete-range-btn', 'DELETE_RANGE');
  }

  // Apply to all general delete buttons with confirm attribute
  applyDeleteConfirmation('a[data-confirm], button[data-confirm]', 'DELETE_DOCUMENT');
});