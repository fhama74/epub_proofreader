import {useEffect,useState} from 'react';
const query='(max-width: 1100px), (pointer: coarse)';
export default function useReaderLayout(){
 const [readerHeight,setReaderHeight]=useState(()=>window.visualViewport?.height ?? window.innerHeight);
 useEffect(()=>{const resize=()=>setReaderHeight(window.visualViewport?.height ?? window.innerHeight);window.addEventListener('resize',resize);window.visualViewport?.addEventListener('resize',resize);return()=>{window.removeEventListener('resize',resize);window.visualViewport?.removeEventListener('resize',resize);};},[]);
 const [compact,setCompact]=useState(()=>window.matchMedia(query).matches);
 const [preference,setPreference]=useState<boolean|null>(()=>{try{const v=localStorage.getItem('eproof-reader-mode');return v==='reader'?true:v==='workspace'?false:null;}catch{return null;}});
 useEffect(()=>{const media=window.matchMedia(query);const change=()=>setCompact(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
 function choose(value:boolean){setPreference(value);try{localStorage.setItem('eproof-reader-mode',value?'reader':'workspace');}catch{}}
 return {readerMode:preference??compact,chooseReader:choose,readerHeight};
}
