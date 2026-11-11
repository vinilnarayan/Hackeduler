/** POC emails: one or more addresses separated by commas, semicolons or spaces (max 10). */
export function splitEmails(v: string): string[] {
  return v.split(/[,;\s]+/).filter(Boolean)
}

export function validPocEmails(v: string): boolean {
  const parts = splitEmails(v)
  return parts.length > 0 && parts.length <= 10 && parts.every((p) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(p))
}
