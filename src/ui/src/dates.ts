/**
 * Months spelled out: en-GB ICU data gives *Sept*, where staging labels (`%b`) say *Sep*.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function dayMonth(when: Date): string {
  return `${when.getDate()} ${MONTHS[when.getMonth()]}`;
}

export function clock(when: Date): string {
  return when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
