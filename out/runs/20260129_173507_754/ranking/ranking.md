# Ranking sheet
Run group: 20260129_173507_754
Seed: 1770028257886

Instructions:
- For each prompt, you will see responses labeled A/B/C (order is random).
- Rank them from best to worst in the CSV.
- In the CSV, put the best label in rank1, the second-best in rank2, and the worst in rank3.
- Use each label only once per prompt (no repeats).
- Fill and return answers.csv (delimiter is ';').

Example row:
prompt_id;rank1;rank2;rank3
p1;B;C;A

Important: only send back the filled answers CSV (you may rename it like answers_manolito.csv).

## Prompt p1

Create a profile about a user that wants to set up the eduroam on his device but he is unable to do so, use as variables the different ways he could try to set it up.

### Response A

> Sure! Here’s a profile for a user who is trying to set up eduroam on their device but is facing difficulties. This profile includes various methods they might attempt to connect, along with the necessary structure.
>
> ```yaml
> test_name: "eduroam_setup_assistance"
>
> llm:
>   temperature: 0.7
>   model: gpt-4o
>   model_prov: openai
>   format:
>     type: text
>
> user:
>   language: English
>   role: "A user trying to set up eduroam on their device but facing issues."
>   context:
>     - "The user is a student or staff member at an educational institution."
>     - "They have previously connected to Wi-Fi networks but are unfamiliar with eduroam."
>   goals:
>     - "I want to connect to eduroam using {{setup_method}}."
>     - setup_method:
>         function: random()
>         type: string
>         data: [manual configuration, using the eduroam app, scanning a QR code, connecting via a web portal, using a configuration file]
>
> chatbot:
>   is_starter: false
>   fallback: "I'm sorry, could you provide more details about the issue you're facing?"
>   output:
>     - connection_status:
>         type: string
>         description: "The status of the connection attempt, such as success, failure, or error message."
>     - troubleshooting_steps:
>         type: string
>         description: "The steps taken by the user to try and connect to eduroam, including any error messages received."
>
> conversation:
>   number: 3
>   goal_style:
>     steps: 5
>   interaction_style:
>     - random:
>       - long phrases
>       - make spelling mistakes
>       - single questions
> ```
>
> Feel free to modify any part of it to better suit your needs! If you have any other requests or need further assistance, just let me know! 😊

### Response B

> Great! I've loaded the relevant documentation for SENSEI profiles from the `sensei-chat-guide.md`. Now, let's create a profile for a user who wants to set up eduroam on their device but is facing difficulties. 
>
> ### Profile Structure
> We'll define the profile with the following sections:
> - **User Role**: Describes the user trying to set up eduroam.
> - **Goals**: Lists the different ways the user could attempt to set it up.
> - **Chatbot Output**: Defines what information we want to extract after the conversation.
>
> ### Proposed Profile YAML
> Here’s a draft of the profile:
>
> ```yaml
> test_name: "eduroam_setup_assistance"
>
> llm:
>   temperature: 0.7
>   model: gpt-4o
>   model_prov: openai
>   format:
>     type: text
>
> user:
>   language: English
>   role: "A user trying to set up eduroam on their device."
>   context:
>     - "The user is unsure about the setup process and needs guidance."
>   goals:
>     - "Try to set up eduroam using the device's Wi-Fi settings."
>     - "Check the university's website for instructions."
>     - "Contact the IT support for assistance."
>     - "Look for a tutorial video online."
>     - "Ask peers for help with the setup."
>
> chatbot:
>   is_starter: true
>   fallback: "I'm sorry, I didn't understand that. Can you try again?"
>   output:
>     - setup_method:
>         type: string
>         description: "The method the user chose to attempt the setup."
>     - success:
>         type: boolean
>         description: "Whether the user successfully set up eduroam."
>
> conversation:
>   number: combinations(0.5, pairwise)
>   goal_style:
>     steps: 5
>   interaction_style:
>     - random:
>       - long phrases
>       - make spelling mistakes
> ```
>
> ### Explanation of the Profile
> - **Goals**: The user can try different methods to set up eduroam, which are listed in the `goals` section.
> - **Chatbot Output**: The `setup_method` field will capture which method the user chose, and `success` will indicate if the setup was successful.
> - **Conversation Control**: The conversation will use a combination of methods to ensure diverse interactions.
>
> Would you like to proceed with creating this profile, or do you have any modifications in mind? 😊

### Response C

> Sure! Here’s a profile for a user who is trying to set up the eduroam network on their device but is facing difficulties. This profile includes various methods they might attempt to set it up as variables. Feel free to adjust any details to better fit your needs! 😊
>
> ```yaml
> test_name: "eduroam_setup_assistance"
>
> llm:
>   temperature: 0.5
>   model: gpt-4o
>   model_prov: openai
>   format:
>     type: text
>
> user:
>   language: English
>   role: "A student trying to set up the eduroam network on their device."
>   context:
>     - "You are at a university and need to connect to the eduroam Wi-Fi network."
>     - "You have tried multiple methods but are still unable to connect."
>   goals:
>     - "Try to set up eduroam using the {{setup_method}}."
>     - "Ask for help if the setup fails."
>     - setup_method:
>         function: random()
>         type: string
>         data: [manual configuration, using the eduroam configuration tool, scanning the QR code, checking network settings, resetting network settings]
>
> chatbot:
>   is_starter: true
>   fallback: "I'm sorry, I didn't quite understand. Can you tell me more about the issue you're facing with eduroam?"
>   output:
>     - setup_status:
>         type: string
>         description: "The status of the eduroam setup attempt, e.g., success or failure."
>     - troubleshooting_steps:
>         type: string
>         description: "Any troubleshooting steps provided by the chatbot."
>
> conversation:
>   number: 3
>   goal_style:
>     all_answered:
>       export: true
>       limit: 10
>   interaction_style:
>     - random:
>       - long phrases
>       - change your mind
>       - single questions
> ```
>
> This profile sets up a scenario where the user can explore different methods for connecting to eduroam, and it allows for interaction with the chatbot to troubleshoot and assist with the setup process. Let me know if you need any more adjustments or additional details! 🌟

## Prompt p2

We need a profile to mimic an erasmus user that just came and doesn't know how to setup his Moodle, Sigma, etc. We don't need many input variables but we do need chatbout outputs to check that we get proper support.

### Response A

> That sounds like a great idea! Let's create a simple profile for an Erasmus user who needs help setting up their Moodle and Sigma accounts. This profile will focus on the necessary outputs to ensure they receive proper support.
>
> Here's a basic profile structure you can use:
>
> ```yaml
> test_name: "Erasmus_User_Support"
>
> llm:
>   temperature: 0.7
>   model: gpt-4o
>   model_prov: openai
>   format:
>     type: text
>
> user:
>   language: English
>   role: "You are an Erasmus student who has just arrived and needs help setting up your Moodle and Sigma accounts."
>   context:
>     - "You are unfamiliar with the university's digital platforms."
>   goals:
>     - "Ask for help on how to set up Moodle."
>     - "Request instructions for accessing Sigma."
>     - "Inquire about any necessary institutional accounts."
>
> chatbot:
>   is_starter: false
>   fallback: "I'm sorry, I didn't understand that. Can you please rephrase?"
>   output:
>     - moodle_setup_instructions:
>         type: string
>         description: "Instructions for setting up Moodle."
>     - sigma_access_instructions:
>         type: string
>         description: "Instructions for accessing Sigma."
>     - institutional_account_info:
>         type: string
>         description: "Information regarding the need for an institutional account."
>
> conversation:
>   number: 2
>   goal_style:
>     steps: 3
>   interaction_style:
>     - long phrases
>     - make spelling mistakes
> ```
>
> ### Explanation:
> - **Goals**: The user will ask for help with Moodle and Sigma, ensuring they get the necessary support.
> - **Outputs**: The chatbot will provide instructions for setting up Moodle, accessing Sigma, and information about any required institutional accounts.
> - **Conversation Style**: The interaction style includes long phrases and potential spelling mistakes to mimic a real user's behavior.
>
> Feel free to adjust any part of this profile to better fit your needs! 😊

### Response B

> That sounds like a great idea! To create a profile for an Erasmus user who needs support with setting up platforms like Moodle and Sigma, we should define the necessary chatbot outputs that will help provide that support.
>
> ### Suggested Chatbot Outputs
> Here are some outputs we might consider including in the profile:
>
> - **greeting**: A friendly welcome message.
> - **setup_instructions**: Detailed instructions on how to set up Moodle and Sigma.
> - **faq**: Answers to frequently asked questions related to the platforms.
> - **contact_support**: Information on how to contact support if further assistance is needed.
>
> ### Next Steps
> 1. **Define the Outputs**: We need to finalize the outputs we want in the profile.
> 2. **Create the Profile**: Once we have the outputs defined, I can help you create the profile in YAML format.
>
> Would you like to proceed with these suggested outputs, or do you have any additional outputs in mind? 😊

### Response C

> Creating a profile for an Erasmus user who needs help setting up Moodle and Sigma sounds like a great idea! Let's keep it simple and focused on the essential outputs for validation. Here’s a basic structure you can use for your profile:
>
> ```yaml
> test_name: "Erasmus User Setup Assistance"
>
> llm:
>   temperature: 0.7
>   model: gpt-4o
>   model_prov: openai
>   format:
>     type: text
>
> user:
>   language: Spanish
>   role: "Erasmus student who has just arrived and needs help setting up Moodle and Sigma."
>   context:
>     - "You are unfamiliar with the university's digital platforms and need guidance."
>   goals:
>     - "Solicitar ayuda para configurar mi cuenta en Moodle."
>     - "Pedir instrucciones sobre cómo acceder a Sigma."
>     - "Consultar sobre los requisitos necesarios para utilizar estas plataformas."
>
> chatbot:
>   is_starter: false
>   fallback: "¿Puedes repetir la pregunta de otra forma? O, si lo prefieres, consulta nuestro catálogo de servicios."
>   output:
>     - moodle_setup_info:
>         type: string
>         description: "Instrucciones para configurar la cuenta en Moodle."
>     - sigma_access_info:
>         type: string
>         description: "Pasos para acceder a Sigma."
>     - support_contact_info:
>         type: string
>         description: "Información de contacto para soporte técnico."
>
> conversation:
>   number: 3
>   goal_style:
>     steps: 5
>   interaction_style:
>     - single questions
> ```
>
> ### Explanation:
> - **Test Name**: A clear identifier for your profile.
> - **User Section**: Defines the role and context of the user, focusing on their need for assistance.
> - **Goals**: Specific requests that the user would make regarding Moodle and Sigma.
> - **Chatbot Output**: Specifies the information you want to extract for validation, ensuring you get the necessary support details.
> - **Conversation Controls**: Sets the number of interactions and how the user will engage with the chatbot.
>
> Feel free to adjust any part of this profile to better fit your needs! If you have any questions or need further modifications, just let me know! 😊
