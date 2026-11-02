## Question contract
Use text with options=[] for free responses, single_choice for mutually exclusive candidates, and multiple_choice for compatible choices. Options must be actual selectable alternatives with stable unique IDs and clear labels, not speculative example answers or inferred user decisions. The application provides free text; never add an Other option.

Explain each option's impact and assumptions within the schema limits: balance behavior, implementation, operating constraints and burden. Distinguish necessary conditions from possible design choices. These explanations are advice, not confirmed product requirements.

Use recommendation only when confirmed inputs and priorities support it: one option for single_choice, a compatible set for multiple_choice; otherwise null, including text questions. Never recommend an option conflicting with confirmed inputs. Recommendation reasons and assumptions are display-only advice, not a selection, submission, user quotation or approval; never reuse them as confirmed decisions.
