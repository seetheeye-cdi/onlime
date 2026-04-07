---
date: <% tp.date.now("YYYY-MM-DD") %>
type: daily
author: "[[🙍‍♂️최동인]]"
index: "[[MOC Daily Notes]]"
---
#### [[<% tp.date.now("YYYY-MM-DD", -1) %> |◀︎]] <% tp.date.now("YYYY-MM-DD") %> [[<% tp.date.now("YYYY-MM-DD", 1) %> |▶︎]]

## Morning Brief
> _08:00 자동 생성_

---
## ==잡서


---
## 오늘의 기록
```dataview
TABLE WITHOUT ID
  file.link AS "내용",
  participants AS "사람",
  project AS "프로젝트",
  source AS "출처"
FROM "1. INPUT/<% tp.date.now("YYYY-MM") %>" OR "1. INPUT/Meeting"
WHERE contains(string(date), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(string(created), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(file.name, "<% tp.date.now("YYYYMMDD") %>")
SORT created ASC
```

## 미팅/통화 (Plaud)
```dataview
TABLE WITHOUT ID
  file.link AS "미팅",
  participants AS "참석자"
FROM "1. INPUT/Meeting"
WHERE (source = "plaud" OR type = "meeting") AND (contains(string(date), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(string(created), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(file.name, "<% tp.date.now("YYYYMMDD") %>"))
SORT created ASC
```

## 사람 (오늘)
```dataview
TABLE WITHOUT ID
  rows.file.link AS "기록"
FROM "1. INPUT/<% tp.date.now("YYYY-MM") %>" OR "1. INPUT/Meeting"
WHERE contains(string(date), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(string(created), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(file.name, "<% tp.date.now("YYYYMMDD") %>")
FLATTEN participants AS person
WHERE person != "(me)" AND person != "[[🙍‍♂️최동인]]"
GROUP BY person AS 사람
SORT length(rows) DESC
```

## 프로젝트 (오늘)
```dataview
TABLE WITHOUT ID
  rows.file.link AS "기록"
FROM "1. INPUT/<% tp.date.now("YYYY-MM") %>" OR "1. INPUT/Meeting"
WHERE (contains(string(date), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(file.name, "<% tp.date.now("YYYYMMDD") %>")) AND project
GROUP BY project AS 프로젝트
SORT length(rows) DESC
```

---
## 리뷰
> _23:00 AI 일일 요약_

---
## 액션 아이템
```dataview
TASK
FROM "1. INPUT/<% tp.date.now("YYYY-MM") %>" OR "1. INPUT/Meeting"
WHERE (contains(string(date), "<% tp.date.now("YYYY-MM-DD") %>") OR contains(file.name, "<% tp.date.now("YYYYMMDD") %>")) AND !completed
```

---
#### 생성
```dataview
LIST
FROM ""
WHERE file.cday = date("<% tp.date.now("YYYY-MM-DD") %>") AND !contains(file.folder, "Daily")
```
#### 변형
```dataview
LIST
FROM ""
WHERE file.mday = date("<% tp.date.now("YYYY-MM-DD") %>") AND !contains(file.folder, "Daily") AND file.cday != date("<% tp.date.now("YYYY-MM-DD") %>")
```
