/**
 * The short dates the batch pages print: *27 Sep*, *11:42*.
 *
 * Spelled out rather than asked of `toLocaleDateString("en-GB", { month:
 * "short" })`, which answers *Sept* for September under current ICU data
 * (Chromium's and Node's alike) and three letters for every other month --
 * so the pages said *12 Sept* beside *3 Oct*, where the mockups and every
 * staging label (`batches/staging.py`'s `%b`) say *Sep*.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** `3 Sep`, in local time. */
export function dayMonth(when: Date): string {
  return `${when.getDate()} ${MONTHS[when.getMonth()]}`;
}

/** `11:42`, 24-hour, in local time. */
export function clock(when: Date): string {
  return when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
