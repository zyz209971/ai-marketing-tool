const shapes={
 chat:'<path d="M21 11a8 8 0 0 1-8 8H7l-5 3 1.6-5A8 8 0 0 1 2 11a9 9 0 0 1 19 0Z"/>',
 layers:'<path d="m12 3 10 5-10 5L2 8l10-5Zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',
 box:'<path d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm-9 5 9 5 9-5M12 12v10M7.5 4.5l9 5"/>',
 spark:'<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3ZM21 2v4M19 4h4"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 pencil:'<path d="m16 3 5 5L8 21H3v-5L16 3Zm-2 2 5 5"/>',
 chart:'<path d="M4 3v17h17M8 15l4-5 4 2 5-7"/>',
 target:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
 send:'<path d="m22 2-7 20-4-9L2 9l20-7ZM11 13 22 2"/>',
 menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
 settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
 leaf:'<path d="M20 3C9 2 2 6 4 16s18 7 16-13ZM4 20 16 8"/>',
 file:'<path d="M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8M8 16h6"/>'};
export function icon(name){return `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[name]||shapes.spark}</svg>`;}
