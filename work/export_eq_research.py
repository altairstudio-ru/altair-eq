from pathlib import Path
import json

root=Path(r'K:\AltaiR Studio\Projects\AltaiR EQ')
# Local preparation only. Google Drive export requires a separate explicit
# user approval; this script never copies files to a synchronized folder.
exports=root/'outputs'
data=json.loads((root/'outputs'/'eq-market-catalogue.json').read_text(encoding='utf-8'))['products']
canvas='''import { useState, useHostTheme, Stack, H1, H2, Text, Row, Pill, Table, Link, Divider } from "cursor/canvas";
const products=DATA;
export default function EqMarketResearch(){
 const theme=useHostTheme();
 const [group,setGroup]=useState("");
 const [query,setQuery]=useState("");
 const groups=[...new Set(products.map(p=>p.group))];
 const visible=products.filter(p=>(!group||p.group===group)&&JSON.stringify(p).toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru")));
 return <Stack gap={18} style={{padding:24,maxWidth:1500,margin:"0 auto",color:theme.text.primary,background:theme.bg.editor}}>
 <H1>AltaiR EQ: рынок и направления разработки</H1>
 <Text>6 ноября 2026 · 57 исследовательских позиций, включая отдельные модули и штатные EQ. Официальные документы; собственные измерения плагинов ещё не проводились.</Text>
 <H2>Рекомендуемая гипотеза</H2>
 <Text>Точный ручной EQ, понятное прослушивание изменений и коррекция пары инструментов с заданными пользователем пределами вмешательства. Отдельные элементы уже существуют: преимущество сочетания нужно доказать сравнительными задачами.</Text>
 <Row gap={18} wrap>
 <Stack gap={6} style={{flex:"1 1 230px"}}><H2>Сначала: сравнение</H2><Text>Solo, delta, A/B и фиксированное согласование громкости в одном ясном сценарии. Проверить, сокращает ли он время принятия решения.</Text></Stack>
 <Stack gap={6} style={{flex:"1 1 230px"}}><H2>Затем: контекст</H2><Text>Пара источников через sidechain. Явные ограничения на ослабление и защищаемые области; проверка тела инструмента и атаки.</Text></Stack>
 <Stack gap={6} style={{flex:"1 1 230px"}}><H2>Позже: характер</H2><Text>Музыкальное управление шириной и усилением; одна аппаратная модель только после получения эталонных данных.</Text></Stack>
 </Row><Divider/>
 <H2>Каталог и идеи для проверки</H2>
 <label style={{display:"flex",flexDirection:"column",gap:6,maxWidth:500}}>Поиск по продуктам и идеям<input value={query} onChange={e=>setQuery(e.target.value)} style={{font:"inherit",padding:8,color:theme.text.primary,background:theme.bg.elevated,border:"1px solid "+theme.stroke.primary,borderRadius:4}}/></label>
 <Row wrap gap={8}><Pill active={!group} onClick={()=>setGroup("")}>Все сегменты</Pill>{groups.map(g=><Pill key={g} active={g===group} onClick={()=>setGroup(g)}>{g}</Pill>)}</Row>
 <Text>Показано {visible.length} из {products.length}. Возможности ниже документированы разработчиками; выводы для AltaiR являются исследовательской оценкой.</Text>
 {visible.length>0&&<Table stickyHeader headers={["Продукт / источник","Версия и границы","Документировано","Вывод для AltaiR","Проверить измерением"]} rows={visible.map(p=>[<Link href={p.source}>{p.name}</Link>,p.version_scope,p.documented,p.altair_lesson,p.measurement_question])} style={{maxHeight:650,overflow:"auto"}}/>}
 <Divider/><H2>Что докажет профессиональный уровень</H2>
 <Text>АЧХ и фаза относительно собственной цели; устойчивая автоматизация; динамика на контрольных сигналах; реальные задержка и CPU; восстановление сессий и проверки в DAW. Сравнение предпочтений проводится отдельно от теста слышимости и при зафиксированной громкости.</Text>
 <Text>Полный отчёт содержит разбор референсов, ограничения источников, программу испытаний и отдельную проверку замечания о +6 dB на басе. Код DSP, плагины и Mix Studio в этом исследовании не изменялись.</Text>
 </Stack>;
}
'''.replace('DATA',json.dumps(data,ensure_ascii=False))
source=exports/'AltaiR-EQ-market.canvas.tsx'
source.write_text(canvas,encoding='utf-8')
managed=Path(r'C:\Users\Andrey\.cursor\projects\empty-window\canvases\altair-eq-market.canvas.tsx')
try:
    managed.write_text(canvas,encoding='utf-8')
    print('Managed canvas saved')
except FileNotFoundError:
    print('Managed canvas directory unavailable; portable HTML and canvas source exported')
print('Exports saved:',exports)
