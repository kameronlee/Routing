export type SupportCategory = 'food' | 'housing' | 'mental' | 'school';

export type SupportPlan = {
  category: SupportCategory;
  urgency: 'Review now' | 'Review today' | 'Deadline found' | 'No deadline found';
  title: string;
  plainLanguage: string;
  keyDetails: string[];
  checklist: string[];
  nextSteps: string[];
  confidence: 'High' | 'Medium' | 'Needs review';
  confidenceScore: number;
  whyThisResult: string;
  humanDecision: string;
};

export const SAMPLE_NOTICE =
  'Your student may lose meal benefits unless the household verification form is returned by Friday. Bring proof of address or income if requested.';

const TRAINING_EXAMPLES: Array<{ category: SupportCategory; text: string }> = [
  { category: 'food', text: 'meal benefits food assistance household verification income form lunch application snap ebt' },
  { category: 'food', text: 'family needs groceries pantry school meals nutrition support eligibility' },
  { category: 'food', text: 'free reduced lunch benefit renewal proof of income deadline' },
  { category: 'housing', text: 'eviction notice rent overdue landlord lease court hearing housing assistance' },
  { category: 'housing', text: 'shelter intake utility shutoff rental aid proof of residence' },
  { category: 'housing', text: 'must leave apartment housing eligibility application tenant deadline' },
  { category: 'mental', text: 'student crisis unsafe panic anxiety depression counselor urgent wellness support' },
  { category: 'mental', text: 'self harm immediate danger stress mental health trusted adult counseling' },
  { category: 'mental', text: 'behavior concern safety plan school psychologist same day help' },
  { category: 'school', text: 'attendance letter school form parent signature enrollment transportation notice' },
  { category: 'school', text: 'student records report card meeting permission slip due date' },
  { category: 'school', text: 'school office registration document proof of address guardian response required' },
];

const CATEGORIES: SupportCategory[] = ['food', 'housing', 'mental', 'school'];

const tokenize = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(token => token.length > 1);

const vocabulary = new Set(TRAINING_EXAMPLES.flatMap(example => tokenize(example.text)));
const tokenCounts = new Map<SupportCategory, Map<string, number>>();
const totals = new Map<SupportCategory, number>();

for (const category of CATEGORIES) {
  const counts = new Map<string, number>();
  for (const example of TRAINING_EXAMPLES.filter(item => item.category === category)) {
    for (const token of tokenize(example.text)) counts.set(token, (counts.get(token) || 0) + 1);
  }
  tokenCounts.set(category, counts);
  totals.set(category, [...counts.values()].reduce((sum, count) => sum + count, 0));
}

function classify(text: string) {
  const tokens = tokenize(text);
  const logScores = CATEGORIES.map(category => {
    const counts = tokenCounts.get(category)!;
    const total = totals.get(category)!;
    const prior = TRAINING_EXAMPLES.filter(item => item.category === category).length / TRAINING_EXAMPLES.length;
    const score = tokens.reduce(
      (sum, token) => sum + Math.log(((counts.get(token) || 0) + 1) / (total + vocabulary.size)),
      Math.log(prior),
    );
    return { category, score };
  }).sort((a, b) => b.score - a.score);

  const maxScore = logScores[0].score;
  const probabilities = logScores.map(result => ({
    ...result,
    probability: Math.exp(result.score - maxScore),
  }));
  const denominator = probabilities.reduce((sum, result) => sum + result.probability, 0);
  return probabilities.map(result => ({ ...result, probability: result.probability / denominator }));
}

function deadlineHint(text: string) {
  const match = text.match(
    /\b(today|tomorrow|tonight|(?:by|before|due(?:\s+on)?)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+\d{1,2})?|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b/i,
  );
  return match?.[0];
}

function actionHint(text: string) {
  const match = text.match(
    /\b(return(?:ed)?|submit|complete|sign|bring|provide|upload|send|call|contact|attend)\b[^.!?\n]{0,90}/i,
  );
  return match?.[0].replace(/\s+/g, ' ').replace(/[,;:\s]+$/, '');
}

function documentHints(text: string) {
  const hasCombinedProof = /\bproof of (?:address|residence) or income\b/i.test(text);
  const rules: Array<[RegExp, string]> = [
    [/\bproof of (?:address|residence)\b/i, 'proof of address'],
    [/\bproof of income\b/i, 'proof of income'],
    [/\b(?:photo )?id(?:entification)?\b/i, 'photo identification'],
    [/\bverification form\b/i, 'verification form'],
    [/\bapplication form\b|\bapplication\b/i, 'application'],
    [/\blease\b/i, 'lease'],
    [/\bcourt (?:notice|papers|documents)\b/i, 'court documents'],
    [/\bpermission (?:slip|form)\b/i, 'permission form'],
  ];
  const matches = rules.filter(([pattern]) => pattern.test(text)).map(([, label]) => label);
  return hasCombinedProof
    ? ['proof of address or income', ...matches.filter(label => label !== 'proof of address' && label !== 'proof of income')]
    : [...new Set(matches)];
}

export function analyzeSupportNotice(rawText: string): SupportPlan {
  const text = rawText.trim() || SAMPLE_NOTICE;
  const ranked = classify(text);
  const category = ranked[0].category;
  const score = ranked[0].probability;
  const margin = score - ranked[1].probability;
  const confidence: SupportPlan['confidence'] = score >= 0.72 && margin >= 0.35
    ? 'High'
    : score >= 0.48 && margin >= 0.15
      ? 'Medium'
      : 'Needs review';
  const deadline = deadlineHint(text);
  const requestedAction = actionHint(text);
  const documents = documentHints(text);
  const deadlineStep = deadline ? `Confirm what is due ${deadline}` : 'Find and confirm the exact deadline';
  const actionSentence = requestedAction
    ? `A requested action appears to be: “${requestedAction}.”`
    : 'The requested action is not clear enough for the assistant to confirm.';
  const deadlineSentence = deadline
    ? `The notice mentions “${deadline}.”`
    : 'The assistant could not find a clear deadline.';

  const categoryLabels: Record<SupportCategory, string> = {
    food: 'Food or school-meal support',
    housing: 'Housing support',
    mental: 'Wellness or safety support',
    school: 'School support',
  };
  const keyDetails = [
    `Likely topic: ${categoryLabels[category]}`,
    deadline ? `Deadline mentioned: ${deadline}` : 'Deadline: not clearly found',
    requestedAction ? `Requested action: ${requestedAction}` : 'Requested action: needs human review',
    ...(documents.length ? [`Documents mentioned: ${documents.join(', ')}`] : []),
  ];

  const plans: Record<SupportCategory, Omit<SupportPlan, 'category' | 'confidence' | 'confidenceScore' | 'whyThisResult' | 'keyDetails'>> = {
    food: {
      urgency: deadline ? 'Deadline found' : 'No deadline found',
      title: 'Food-benefit or meal-support notice',
      plainLanguage: `This may be about keeping or applying for food support. ${actionSentence} ${deadlineSentence} Confirm everything with the official office before sharing personal information.`,
      checklist: [deadlineStep, 'Save a photo of the complete notice', 'Gather only the documents the official office confirms', 'Ask a school liaison or benefits worker to review it'],
      nextSteps: ['Contact the school meal-benefits office or food-support desk', 'Ask what happens if a document is missing', 'Use an official number or website before sending sensitive information'],
      humanDecision: 'A benefits worker decides eligibility and required documents - the assistant does not.',
    },
    housing: {
      urgency: 'Review today',
      title: 'Housing or eviction notice',
      plainLanguage: `This may affect where someone can stay. ${actionSentence} ${deadlineSentence} Preserve every page and ask a qualified housing advocate to review it before you sign, pay, or agree to anything.`,
      checklist: [deadlineStep, 'Save every page and envelope', 'Collect the lease and related court papers', 'Contact a housing advocate or intake worker'],
      nextSteps: ['Ask whether there is a response or appeal deadline', 'Do not ignore court dates', 'Get human review before signing anything'],
      humanDecision: 'A housing advocate or court professional interprets rights and deadlines - the assistant does not.',
    },
    mental: {
      urgency: 'Review now',
      title: 'Wellness or safety concern',
      plainLanguage: 'This appears to involve student wellbeing or safety. A trusted adult should review the situation now; if anyone may be in immediate danger, contact local emergency help.',
      checklist: ['Tell a trusted adult what changed', 'Keep the exact message or notice', 'Ask for a same-day counselor or wellness contact', 'Do not leave someone alone if immediate danger is possible'],
      nextSteps: ['Contact a school counselor or trusted adult', 'Share only what is needed to get help', 'Let a trained person make the safety decision'],
      humanDecision: 'A trained person assesses safety and care - the assistant never makes a crisis decision.',
    },
    school: {
      urgency: deadline ? 'Deadline found' : 'No deadline found',
      title: 'School form or support notice',
      plainLanguage: `This may be a school request. ${actionSentence} ${deadlineSentence} Confirm the sender and reply through an official school channel.`,
      checklist: [deadlineStep, 'Find the sender and school office', 'List each form or document requested', 'Ask a family liaison or counselor to check your understanding'],
      nextSteps: ['Reply through an official school channel', 'Bring the notice to the support office', 'Ask for a translated or plain-language copy if needed'],
      humanDecision: 'School staff confirm requirements and make student-support decisions - the assistant does not.',
    },
  };

  const needsReview = confidence === 'Needs review';
  const selectedPlan = needsReview
    ? {
      urgency: deadline ? 'Deadline found' as const : 'No deadline found' as const,
      title: 'Notice needs human review',
      plainLanguage: `The assistant could not confidently identify this notice. ${deadlineSentence} Do not act on a guessed category; keep the complete notice and verify the sender through an official channel.`,
      checklist: [deadlineStep, 'Save every page of the notice', 'Verify the sender using an official phone number or website', 'Ask a trusted staff member or support worker to read it with you'],
      nextSteps: ['Ask a trusted staff member or support worker to review the complete notice', 'Do not send personal information until the sender is verified'],
      humanDecision: 'A trusted person identifies what the notice requires - the assistant does not guess when confidence is low.',
    }
    : plans[category];

  return {
    category,
    ...selectedPlan,
    keyDetails: needsReview
      ? [
        'Likely topic: uncertain - human review needed',
        deadline ? `Deadline mentioned: ${deadline}` : 'Deadline: not clearly found',
        requestedAction ? `Possible requested action: ${requestedAction}` : 'Requested action: not clearly found',
        ...(documents.length ? [`Documents mentioned: ${documents.join(', ')}`] : []),
      ]
      : keyDetails,
    confidence,
    confidenceScore: score,
    whyThisResult: (() => {
      const categoryTerms = tokenCounts.get(category)!;
      const evidence = [...new Set(tokenize(text).filter(token => categoryTerms.has(token)))].slice(0, 4);
      return evidence.length
        ? `Matched notice language such as: ${evidence.join(', ')}. This is a category estimate, not an eligibility or legal decision.`
        : 'Few recognizable support terms were found. Treat this result as uncertain and ask a person to review the complete notice.';
    })(),
  };
}
