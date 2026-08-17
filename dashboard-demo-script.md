# LabTrend — Dashboard Demo Script (5 minutes)

Covers 4 tabs: **Dashboard · Patient Monitoring · Early Warning · Detector Accuracy**
Target: ~700 spoken words ≈ 5:00. Timings are cumulative.

---

## EN

### 0:00–0:40 — Who it's for, and the problem

"What you're seeing is our dashboard, *Clinical Control — Deterioration Watch*.

The user we designed it for is the person on the ward floor: the **attending doctor or the shift nurse** in an internal-medicine ward or an ICU. Today that nurse gets lab results the way the hospital system gives them — a list of numbers, one test at a time. Nobody sits and reads the *trend* across eight different labs over three days, across forty patients.

That's exactly what this does. It reads the labs, scores every admission, and answers one question: **who do I walk to first, and why.** All the data is real — MIMIC-III lab records, thousands of admissions, the numbers at the bottom of the screen show the pipeline stats.

Before the tabs — the left sidebar. That's the **triage worklist**: every admission ranked by risk score, filterable to High / Medium / Low, searchable by patient ID. You pick a patient here, and the four tabs all describe that patient."

### 0:40–1:55 — Tab 1: Dashboard

"**Dashboard** is the single-patient view. 'What is happening with this patient right now.' Five things on it:

1. **The risk index** — one number and one category: Low, Medium or High.
2. **Three counters** — how many labs were recorded this admission, how many are currently critical, how many are actively worsening.
3. **Risk Trajectory** — the score across the entire hospital stay. It's plotted on real elapsed time, so a two-hour gap and a two-day gap don't look the same. And there are two dashed markers on it: the moment we first raised concern, and the moment the first critical value actually appeared. **The distance between those two lines is the whole point of the project.**
4. **'Why this score'** — a full breakdown table: every lab, its latest value, its status, its trend, and exactly how many points it contributed. Nothing here is a black box; a doctor can audit the number.
5. **Early-warning alerts in plain language**, and a grid of **eight mini-charts — one per lab** — where the green band is the normal healthy range, so you see at a glance if the line is leaving it.

And the whole thing exports to a **PDF report** for the patient file."

### 1:55–2:45 — Tab 2: Patient Monitoring

"**Patient Monitoring** is the same patient, but a different question. Not *how bad*, but *what pattern*.

One abnormal lab doesn't tell you much. Several labs moving together do — that's how clinicians actually think. So this page detects **named clinical patterns**: for example, when creatinine and urea rise together, that points at the kidneys, not at eight unrelated numbers.

Each card says in plain words what the pattern means, shows **which labs triggered it**, which ones were expected but are still in range, and — importantly for the seminar — **a link to the published source** the definition came from. Underneath, the live lab charts for context."

### 2:45–3:35 — Tab 3: Early Warning

"**Early Warning** is the question the project actually set out to answer: *how early?*

We take every admission that eventually reached a critically out-of-range value, and we measure how many hours **before** that our score had already escalated. Two bands:
- **First concern** — the score left Low.
- **High-risk alert** — the score hit High.

For each we show the **median lead time in hours**, the **percentage of admissions we warned early on**, plus the 75th percentile and the maximum.

And we're honest about the result: 'first concern' warns much earlier than 'High', because a single critical value is heavy enough to push the score to High by itself — so the High alert tends to arrive *with* the event rather than before it. That gap is exactly the argument for a learned model as the next step."

### 3:35–4:30 — Tab 4: Detector Accuracy

"Last tab — **Detector Accuracy**. This answers: *why should you believe any of the above?*

MIMIC ships its own 'abnormal' flag on every lab value. So we have ground truth. We run our detector against it across every lab value in the dataset and report **accuracy, precision, recall, specificity and F1**, a **confusion matrix** — where we agree, where we over-flag, where we miss — and a **per-lab breakdown**, so you can see which specific tests we're weakest on.

Being able to point at our own false positives is, for us, part of the deliverable."

### 4:30–5:00 — Close

"So the flow is one sentence per tab:
sidebar — **who** to see first;
Dashboard — **what's wrong** with them;
Monitoring — **which clinical pattern** it matches;
Early Warning — **how much time** we bought;
Accuracy — **how much you should trust it.**

It's a fully transparent rule engine — every rule is cited, every score is auditable — and that transparency is exactly what makes it a usable baseline for a learned model later. Happy to take questions."

---

## HE — עברית

### 0:00–0:40 — למי זה מיועד, ומה הבעיה

"מה שאתם רואים זה הדשבורד שלנו — *Clinical Control, ניטור הידרדרות*.

המשתמש שבשבילו בנינו את זה הוא מי שנמצא במחלקה: **הרופא התורן או האחות במשמרת**, במחלקה פנימית או בטיפול נמרץ. היום האחות מקבלת את תוצאות המעבדה כמו שהמערכת של בית החולים נותנת אותן — רשימת מספרים, בדיקה אחת בכל פעם. אף אחד לא יושב וקורא את **המגמה** של שמונה בדיקות שונות לאורך שלושה ימים, על פני ארבעים מטופלים.

בדיוק את זה המערכת עושה. היא קוראת את בדיקות המעבדה, נותנת ציון לכל אשפוז, ועונה על שאלה אחת: **למי אני ניגשת קודם, ולמה.** כל הנתונים אמיתיים — רשומות מעבדה מ-MIMIC-III, אלפי אשפוזים; המספרים בתחתית המסך מציגים את נתוני העיבוד.

לפני הטאבים — הסרגל השמאלי. זה **רשימת הטריאז'**: כל האשפוזים מדורגים לפי ציון סיכון, אפשר לסנן ל-High / Medium / Low ולחפש לפי מספר מטופל. בוחרים כאן מטופל, וכל ארבעת הטאבים מתארים אותו."

### 0:40–1:55 — טאב 1: Dashboard

"**Dashboard** זה המסך של מטופל בודד. 'מה קורה עם המטופל הזה עכשיו'. יש בו חמישה דברים:

1. **מדד הסיכון** — מספר אחד וקטגוריה אחת: Low, Medium או High.
2. **שלושה מונים** — כמה בדיקות נרשמו באשפוז הזה, כמה מהן קריטיות כרגע, וכמה נמצאות במגמת החמרה.
3. **גרף מסלול הסיכון (Risk Trajectory)** — הציון לאורך כל האשפוז. הוא משורטט לפי זמן אמיתי שחלף, כך שפער של שעתיים ופער של יומיים לא נראים אותו דבר. ויש עליו שני קווים מקווקווים: הרגע שבו הרמנו דגל ראשון, והרגע שבו הופיע הערך הקריטי הראשון בפועל. **המרחק בין שני הקווים האלה הוא כל הפרויקט.**
4. **"למה הציון הזה"** — טבלת פירוק מלאה: כל בדיקה, הערך האחרון שלה, הסטטוס, המגמה, וכמה נקודות בדיוק היא הוסיפה. שום דבר כאן הוא לא קופסה שחורה — רופא יכול לבדוק את המספר בעצמו.
5. **התראות בשפה פשוטה**, ורשת של **שמונה גרפים קטנים — אחד לכל בדיקה** — כשהפס הירוק הוא הטווח התקין, כך שרואים במבט אחד אם הקו יוצא ממנו.

ואת הכל אפשר לייצא ל**דוח PDF** לתיק המטופל."

### 1:55–2:45 — טאב 2: Patient Monitoring

"**Patient Monitoring** זה אותו מטופל, אבל שאלה אחרת. לא *כמה חמור*, אלא *איזו תבנית*.

בדיקה חריגה אחת לא אומרת הרבה. כמה בדיקות שזזות יחד — כן, וככה רופאים באמת חושבים. אז הדף הזה מזהה **תבניות קליניות בעלות שם**: למשל, כשקריאטינין ואוריאה עולים ביחד, זה מצביע על הכליות — ולא על שמונה מספרים לא קשורים.

כל כרטיס מסביר במילים פשוטות מה התבנית אומרת, מראה **אילו בדיקות הפעילו אותה**, אילו היינו מצפים לראות אבל הן עדיין בטווח, ו — וזה חשוב לסמינר — **קישור למקור המחקרי** שממנו לקוחה ההגדרה. מתחת, גרפי המעבדה החיים להקשר."

### 2:45–3:35 — טאב 3: Early Warning

"**Early Warning** זו השאלה שהפרויקט באמת בא לענות עליה: *כמה מוקדם?*

לקחנו כל אשפוז שהגיע בסופו של דבר לערך קריטי, ומדדנו כמה שעות **לפני כן** הציון שלנו כבר עלה. שני מדדים:
- **First concern** — הציון יצא מ-Low.
- **High-risk alert** — הציון הגיע ל-High.

לכל אחד אנחנו מציגים את **חציון זמן ההתראה בשעות**, את **אחוז האשפוזים שקיבלו התראה מוקדמת**, וגם אחוזון 75 והמקסימום.

ואנחנו הוגנים לגבי התוצאה: 'First concern' מתריע הרבה יותר מוקדם מ-High, כי ערך קריטי בודד מספיק כבד כדי לדחוף לבד את הציון ל-High — ולכן התראת ה-High נוטה להגיע *יחד* עם האירוע ולא לפניו. הפער הזה הוא בדיוק הנימוק למודל לומד בשלב הבא."

### 3:35–4:30 — טאב 4: Detector Accuracy

"הטאב האחרון — **Detector Accuracy**. הוא עונה על: *למה בכלל להאמין לכל מה שהראינו?*

ל-MIMIC יש דגל 'abnormal' משלו על כל ערך מעבדה. כלומר יש לנו אמת מוסכמת. אנחנו מריצים את הגלאי שלנו מולה על כל ערכי המעבדה בדאטהסט ומדווחים **Accuracy, Precision, Recall, Specificity ו-F1**, **מטריצת בלבול** — איפה אנחנו מסכימים, איפה אנחנו מסמנים יותר מדי, ואיפה פספסנו — ו**פירוק לפי בדיקה**, כדי לראות באילו בדיקות ספציפיות אנחנו הכי חלשים.

היכולת להצביע על ה-False Positives של עצמנו היא מבחינתנו חלק מהתוצר."

### 4:30–5:00 — סיכום

"אז הזרימה היא משפט אחד לכל טאב:
הסרגל — **למי** ניגשים קודם;
Dashboard — **מה** לא בסדר אצלו;
Monitoring — **לאיזו תבנית קלינית** זה מתאים;
Early Warning — **כמה זמן** הרווחנו;
Accuracy — **כמה אפשר לסמוך** על זה.

זה מנוע חוקים שקוף לחלוטין — כל חוק מגובה במקור, כל ציון ניתן לבדיקה — והשקיפות הזו היא בדיוק מה שהופך אותו לבסיס טוב למודל לומד בהמשך. אשמח לשאלות."

---

## Delivery notes (what to click, when)

| Time | Say | Click |
|---|---|---|
| 0:00 | intro | stay on Dashboard, gesture at the sidebar |
| 0:20 | triage worklist | click High / Medium filter, then pick a **High** patient with alerts |
| 0:40 | Dashboard tour | scroll: score card → trajectory → why-this-score → alerts → lab grid |
| 1:40 | mention PDF | hover **Export Patient Report** (don't actually download) |
| 1:55 | Monitoring | click **Patient Monitoring** |
| 2:45 | Early Warning | click **Early Warning** |
| 3:35 | Accuracy | click **Detector Accuracy** |
| 4:30 | close | leave it on Detector Accuracy or go back to Dashboard |

**Pre-demo checklist**
- Pick the demo patient in advance — one with High risk, ≥1 detected syndrome, and a visible gap between the "concern" and "critical" dashed lines. Otherwise the strongest point of the talk has nothing to point at.
- Have the API running before you walk in; a "Couldn't load — is the API running?" placeholder costs you a minute.
- If you're short on time, cut the PDF mention (0:15) and the per-lab breakdown detail (0:15).
