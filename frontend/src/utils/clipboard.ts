/**
 * Clipboard helper with signature flexibility compliant with MarketPulse GEMINI.md Rule 2:
 * Supports both single-argument `(text)` and dual-argument `(label, text)` signatures
 * to prevent TypeError exceptions across varying button handler signatures.
 */
export function copyTextToClipboard(arg1: string, arg2?: string): Promise<boolean> {
  const textToCopy = arg2 !== undefined ? arg2 : arg1;
  if (!textToCopy) return Promise.resolve(false);

  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard
      .writeText(textToCopy)
      .then(() => true)
      .catch((err) => {
        console.error('Failed to copy to clipboard via navigator.clipboard:', err);
        return fallbackCopyTextToClipboard(textToCopy);
      });
  }
  return Promise.resolve(fallbackCopyTextToClipboard(textToCopy));
}

function fallbackCopyTextToClipboard(text: string): boolean {
  try {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand('copy');
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    console.error('Fallback clipboard copy failed:', err);
    return false;
  }
}
