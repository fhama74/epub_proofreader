/** Keep custom zoom within the persisted PDF settings range. */
export const pinchZoom=(scale:number,distance:number,initialDistance:number)=>Math.max(.1,Math.min(5,scale*distance/Math.max(1,initialDistance)));
/** Bound the canvas buffer to avoid Safari's large-canvas blank pages. */
export const pdfOutputRatio=(width:number,height:number,deviceRatio:number)=>Math.min(deviceRatio || 1,8192/width,8192/height,Math.sqrt(16000000/(width*height)));
