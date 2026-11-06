export type ContentType = 'video' | 'post' | 'web' | 'note';
export type View = 'home' | 'all' | 'recent' | 'favorites' | 'collections' | 'collection';
export type Display = 'grid' | 'list';
export type Sort = 'new' | 'old' | 'title';
export type ContentItem = {
  id: number | string;
  title: string;
  platform: string;
  type: ContentType;
  collection: string;
  date: string;
  tags: string[];
  art: string;
  favorite: boolean;
  description: string;
  url: string;
};
export type Collection = {id: string; name: string; color: string; bg: string; ink: string};
export const namedType: Record<ContentType, string> = {video:'영상',post:'게시물',web:'웹페이지',note:'메모'};
export const typeIcon: Record<ContentType, string> = {video:'video',post:'image',web:'link',note:'note'};
export const formatDate = (s: string) => { const d = new Date(`${s}T12:00:00`); return `${d.getMonth()+1}월 ${d.getDate()}일`; };
export const seedCollections: Collection[] =[{id:'design',name:'디자인 레퍼런스',color:'#DDB8E5',bg:'#F6EAF9',ink:'#9562A1'},{id:'develop',name:'개발 노트',color:'#B3D5F1',bg:'#EAF3FC',ink:'#608EB5'},{id:'life',name:'일상과 영감',color:'#E6CA9C',bg:'#FBF1DE',ink:'#A27C45'},{id:'travel',name:'여행 아이디어',color:'#B9D3BD',bg:'#E9F4EA',ink:'#6F9E78'}];
export const seedItems: ContentItem[] =[
 {id:1,title:'피그마 오토레이아웃 제대로 이해하기',platform:'YouTube',type:'video',collection:'design',date:'2026-11-03',tags:['피그마','UI 디자인'],art:'figma',favorite:true,description:'피그마 오토레이아웃의 정렬, 간격, 리사이징 개념을 설명한 영상 콘텐츠 예시입니다.',url:''},
 {id:2,title:'작은 브랜드를 위한 웹 디자인 레퍼런스',platform:'Instagram',type:'post',collection:'design',date:'2026-11-02',tags:['웹 디자인','브랜딩'],art:'editorial',favorite:false,description:'미니멀한 타이포그래피와 따뜻한 컬러를 사용한 브랜드 웹 디자인 모음입니다.',url:''},
 {id:3,title:'도쿄에서 발견한 조용한 카페 공간',platform:'Web',type:'web',collection:'travel',date:'2026-11-01',tags:['도쿄','카페'],art:'cafe',favorite:false,description:'일본 여행에서 방문해 보고 싶은 작은 카페와 인테리어 레퍼런스입니다.',url:''},
 {id:4,title:'React 컴포넌트 설계할 때 생각할 것들',platform:'Web',type:'web',collection:'develop',date:'2026-10-29',tags:['React','프론트엔드'],art:'code',favorite:true,description:'리액트 컴포넌트의 책임 분리와 재사용성을 다루는 개발 아티클 예시입니다.',url:''},
 {id:5,title:'컬러 팔레트에서 시작하는 디자인 시스템',platform:'Instagram',type:'post',collection:'design',date:'2026-10-27',tags:['디자인 시스템'],art:'palette',favorite:false,description:'색상 토큰과 컴포넌트의 관계를 살펴보는 디자인 참고 콘텐츠입니다.',url:''},
 {id:6,title:'언젠가 가보고 싶은 초록빛 숲길',platform:'Web',type:'web',collection:'travel',date:'2026-10-26',tags:['여행','자연'],art:'nature',favorite:true,description:'고요한 숲길과 자연 풍경을 모아둔 여행 영감 콘텐츠입니다.',url:''},
 {id:7,title:'한 접시로 완성하는 주말 파스타',platform:'YouTube',type:'video',collection:'life',date:'2026-10-25',tags:['레시피','요리'],art:'food',favorite:false,description:'간단한 재료로 만드는 주말 파스타 레시피 영상입니다.',url:''},
 {id:8,title:'좋은 인터페이스를 만드는 여백의 규칙',platform:'Web',type:'web',collection:'design',date:'2026-10-23',tags:['UI/UX','레이아웃'],art:'typography',favorite:false,description:'여백과 시각적 계층 구조를 정리한 디자인 글 예시입니다.',url:''},
 {id:9,title:'TypeScript 타입 정리 노트',platform:'Memo',type:'note',collection:'develop',date:'2026-10-21',tags:['TypeScript','공부'],art:'typescript',favorite:false,description:'유니언 타입과 인터페이스의 차이를 개인적으로 정리한 메모입니다.',url:''},
 {id:10,title:'책상 위 작은 기록들, 워크스페이스 아이디어',platform:'Instagram',type:'post',collection:'life',date:'2026-10-19',tags:['공간','영감'],art:'workspace',favorite:false,description:'따뜻하고 정돈된 작업 공간을 위한 인테리어 아이디어입니다.',url:''},
 {id:11,title:'애니메이션을 부드럽게 만드는 CSS 원리',platform:'YouTube',type:'video',collection:'develop',date:'2026-10-18',tags:['CSS','애니메이션'],art:'motion',favorite:true,description:'CSS transition과 animation으로 자연스러운 인터랙션을 만드는 방법입니다.',url:''},
 {id:12,title:'나중에 다시 찾고 싶은 문장들',platform:'Memo',type:'note',collection:'life',date:'2026-10-15',tags:['글쓰기','기록'],art:'note',favorite:false,description:'떠오른 문장과 생각을 짧게 기록한 메모입니다.',url:''}
 ];
