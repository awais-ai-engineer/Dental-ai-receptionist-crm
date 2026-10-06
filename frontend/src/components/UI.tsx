import { createContext, ReactNode, useContext, useEffect, useState } from 'react';
import { CheckCircle2, X } from 'lucide-react';

type Toast = { id:number; message:string };
const ToastContext=createContext<(message:string)=>void>(()=>{});
export const useToast=()=>useContext(ToastContext);
export function ToastProvider({children}:{children:ReactNode}){const [items,setItems]=useState<Toast[]>([]);const add=(message:string)=>{const id=Date.now();setItems(x=>[...x,{id,message}]);setTimeout(()=>setItems(x=>x.filter(t=>t.id!==id)),3200)};return <ToastContext.Provider value={add}>{children}<div className="toastStack" aria-live="polite">{items.map(t=><div className="toast" key={t.id}><CheckCircle2/>{t.message}</div>)}</div></ToastContext.Provider>}
export function Modal({open,title,onClose,children}:{open:boolean;title:string;onClose:()=>void;children:ReactNode}){useEffect(()=>{const fn=(e:KeyboardEvent)=>e.key==='Escape'&&onClose();document.addEventListener('keydown',fn);return()=>document.removeEventListener('keydown',fn)},[onClose]);if(!open)return null;return <div className="modalBack" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><section className="modal" role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button className="uiIcon" onClick={onClose} aria-label="Close"><X/></button></header>{children}</section></div>}
export function Button({children,variant='primary',className='',...props}:{children:ReactNode;variant?:'primary'|'secondary'|'ghost'|'danger';className?:string}&React.ButtonHTMLAttributes<HTMLButtonElement>){return <button className={`uiButton ${variant} ${className}`} {...props}>{children}</button>}
