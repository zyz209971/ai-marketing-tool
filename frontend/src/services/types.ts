export type Platform = 'xiaohongshu' | 'douyin' | 'wechat_official_account';
export type Status = 'pending' | 'processing' | 'succeeded' | 'failed';
export interface Product {id:string;name:string;price:string|null;selling_points:string[]}
export interface GenerateRequest {brand:{id:string;name:string;description:string;positioning?:string;style?:string};marketing_goal:'new_product'|'promotion'|'brand_awareness'|'holiday';products:Product[];platforms:Platform[];generation_mode:'text_only'|'text_and_image'|'image_only';product_strategy:'merged'|'separate';theme?:string;promotion_rules?:string;activity_time?:string;additional_selling_points?:string;style_requirements?:string;reference_poster?:string}
export interface Content {id?:string;platform:Platform;title:string;body:string;summary?:string;hashtags:string[];product_label?:string;product_ids?:string[];mock?:boolean;references?:{document_id:string;title:string;platform:string}[]}
export interface GenerateResponse {status:Status;contents:Content[];error?:string;mock?:boolean}
export interface ProductSearchRequest {client_brand_id:string;query:string;limit:number;semantic?:boolean}
export interface ProductSearchResponse {products:Product[]}

export interface RetrievalOptions {enabled:boolean;strategy:'hybrid'|'semantic'|'keyword';top_k:number}
export interface ImageRequest {campaign:GenerateRequest;content:{id:string;platform:Platform;title:string;body:string;product_label:string;product_ids?:string[]};purpose:'post_image'|'article_cover'}
export interface TaskResponse {task_id?:string;status:Status;error?:string}
export interface ImageResponse extends TaskResponse {image?:{url?:string;base64?:string;format?:string;mock?:boolean};final_prompt?:string;parsed_prompt?:Record<string,string>;mock?:boolean}
export interface CopyResponse extends TaskResponse {contents:Content[]}
export interface RewriteResponse extends TaskResponse {content:Content}
export type ImageState='not_requested'|'processing'|'succeeded'|'failed'|'mock';
