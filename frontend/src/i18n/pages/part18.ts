// Part 18: owner change list -- shared strings (18.2 one mailbox, and later items).
export const en = {
  "mailbox.one.title": "Company mailbox",
  "mailbox.one.body": "The one email account the app sends from and reads replies from. It works with any provider (Gmail, Outlook, Zoho and others) using its SMTP and IMAP details.",
  "mailbox.one.all_modules": "Used for every module: interview emails, candidate replies, applications, salary and document forms, offers, onboarding, reports and alerts. There is nothing to set per module.",
  "health.title": "Configuration health",
  "health.recheck": "Re-check now",
  "health.rechecking": "Checking…",
  "health.checked_at": "Checked at {time}",
} as const;

export const hi: Partial<Record<keyof typeof en, string>> = {
  "mailbox.one.title": "कंपनी मेलबॉक्स",
  "mailbox.one.body": "वह एक ईमेल खाता जिससे ऐप ईमेल भेजता है और जवाब पढ़ता है। यह किसी भी प्रदाता (Gmail, Outlook, Zoho आदि) के SMTP और IMAP विवरण से काम करता है।",
  "mailbox.one.all_modules": "हर मॉड्यूल के लिए इस्तेमाल होता है: इंटरव्यू ईमेल, उम्मीदवारों के जवाब, आवेदन, वेतन और दस्तावेज़ फ़ॉर्म, ऑफ़र, ऑनबोर्डिंग, रिपोर्ट और सूचनाएँ। हर मॉड्यूल के लिए अलग कुछ सेट नहीं करना है।",
  "health.title": "कॉन्फ़िगरेशन की स्थिति",
  "health.recheck": "अभी फिर से जाँचें",
  "health.rechecking": "जाँच रहे हैं…",
  "health.checked_at": "{time} पर जाँचा गया",
};

export const ta: Partial<Record<keyof typeof en, string>> = {
  "mailbox.one.title": "நிறுவன அஞ்சல் பெட்டி",
  "mailbox.one.body": "செயலி மின்னஞ்சல் அனுப்பவும் பதில்களைப் படிக்கவும் பயன்படுத்தும் ஒரே மின்னஞ்சல் கணக்கு. எந்த வழங்குநரும் (Gmail, Outlook, Zoho போன்றவை) SMTP, IMAP விவரங்களுடன் வேலை செய்யும்.",
  "mailbox.one.all_modules": "ஒவ்வொரு தொகுதிக்கும் பயன்படுகிறது: நேர்காணல் மின்னஞ்சல்கள், விண்ணப்பதாரர் பதில்கள், விண்ணப்பங்கள், சம்பள மற்றும் ஆவணப் படிவங்கள், சலுகைகள், சேர்க்கை, அறிக்கைகள், எச்சரிக்கைகள். ஒவ்வொரு தொகுதிக்கும் தனியாக அமைக்க எதுவும் இல்லை.",
  "health.title": "அமைப்பு நிலை",
  "health.recheck": "இப்போது மீண்டும் சரிபார்",
  "health.rechecking": "சரிபார்க்கிறோம்…",
  "health.checked_at": "{time} இல் சரிபார்க்கப்பட்டது",
};
