export interface Ruby { xpath: string; base: string; readings: string[]; editable: boolean; original_xml: string }
export interface Sentence {index:number;start:number;end:number;text:string}
export interface ProofUnit {paragraph_id:string;paragraph_index:number;kind:'paragraph'|'sentence';sentence_index:number|null;text:string}
export interface ReviewSummary {total:number;done:number;confirmed:boolean;units:boolean[]}
export interface Paragraph {token?:string;chapter_token?:string;review_state?:Record<'body'|'ruby',ReviewSummary>; character_count:number;sentences:Sentence[];unit_mode:'paragraph'|'sentence';structure_editable:boolean; id: string; xpath: string; text: string; original_xml: string; original_text: string; current_xml: string; edited: boolean; rubies: Ruby[]; status: 'unchecked' | 'ai_checked' | 'human_checked' | 'review'; revision: number }
export interface Chapter {heading_level?:number;headings: (Paragraph & {next_paragraph_index:number})[];writing_mode?:'horizontal-tb'|'vertical-rl'|'vertical-lr';proof_units:ProofUnit[];paragraph_count:number;sentence_count:number;long_paragraph_count:number; id: string; path: string; title: string; paragraphs: Paragraph[] }
export interface ProofScore {book_id:string;version:number;total:number;reviewed:number;ai_completed:boolean;ai_points:number;review_points:number;score:number}
export interface Book {proof_score?:ProofScore;import_repairs?:{path:string;line:number;kind:string;before:string;after:string}[];catalog?:Catalog;project?:Project;focus_paragraph_id?:string; edit_state: {revision: number; can_undo: boolean; can_redo: boolean; edit_count: number; history_count: number}; id: string; fingerprint: string; metadata: Record<string, string[]>; chapters: Chapter[]; warnings: string[]; direction: string; file_count: number; toc: {label: string; path: string; fragment: string}[]; manifest: {id: string; path: string; media_type: string}[] }
// Future mutations address a text node by XPath plus revision. Never replace a chapter with HTML from the preview.
export interface TextPatch { paragraphId: string; xpath: string; revision: number; before: string; after: string; source: 'manual' | 'ai'; reason: string }
export interface PdfMapping { paragraphId: string; pages: {page: number; rectangle?: [number, number, number, number]}[] }
export type ProofStatus='unchecked'|'ai_checked'|'human_checked'|'review';
export interface PdfSettings {followText?:boolean;page:number;zoom:number;mode:'width'|'page'|'custom';scrollLeft:number;scrollTop:number}
export interface WorkspaceView {chapterId?:string;paragraphId?:string;sentenceIndex?:number|null;fontSize:number;left:number;right:number;hidePdf:boolean;hideInfo:boolean;epubScroll?:number|null;pdf:PdfSettings}
export interface Mapping {page:number;rectangle?:[number,number,number,number]|null;pdf_sha256:string}
export interface Draft {paragraphToken?:string;rubyRange?:{index:number;start:number;end:number;baseBefore:string;readingBefore:string};revision:number;text:string;rubies:Record<string,{base:string;reading:string}>;reason:string;paragraphId:string;sentenceIndex?:number;before:string}
export interface Project {proof_score?:ProofScore;schema_version:number;version:number;reviews?:Record<string,Record<string,Record<string,string>>>;statuses:Record<string,ProofStatus>;mappings:Record<string,Mapping[]>;drafts:Record<string,Draft>;view:Partial<WorkspaceView>;candidates:unknown[];pdf:{name:string;size:number;sha256:string}|null;progress?:Record<string,number>}
export interface Catalog {filename:string;uploaded_at:string|null;version_base:number;published_version:number}
export interface Publication {version:number;published_at:string;revision:number;sha256:string;size:number;request_id:string;validation:{epubcheck:{status:string};internal:{status:string}}}
export interface LibraryItem extends Catalog {proof_score?:ProofScore;id:string;revision:number;edit_count:number;pdf_attached:boolean;size:number}
