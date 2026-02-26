from app.yaml_validation import validate_answer_yaml_status


def test_rule_validation_accepts_multiple_list_indented_fenced_yaml_blocks():
    answer_text = """It looks like you have a profile named **"Usuarios Nuevos y Admisiones"**.

### Suggested Rules

1. Rule one
   ```yaml
   name: check_admission_links
   description: Ensure that the chatbot provides links for admission processes.
   conversations: 1
   oracle: 'admission_to_grados_link is not None and waitlist_info_link is not None'
   ```

2. Rule two
   ```yaml
   name: validate_future_students_info
   description: Ensure that future students information is provided.
   conversations: 1
   oracle: 'future_students_info is not None'
   ```
"""

    assert validate_answer_yaml_status("rule", answer_text) == "valid"


def test_profile_validation_preserves_normal_yaml_indentation_inside_fence():
    answer_text = """It looks like there are a couple of issues in your profile that we can fix.

Here’s the revised profile:

```yaml
test_name: qa

llm:
  temperature: 0.7
  model: gpt-4o-mini

user:
  language: English
  role: you have to act as a user talking to a virtual assistant of a bike shop
  context:
    - You are interested in asking the items below.
    - Just stick to asking opening times, prices of tire, price of tune-up, price of seat, and actions to the care of bike. Do not ask anything else.
  goals:
    - "opening and closing time of the bike shop"
    - "Which is the price of a new tire?"
    - "Which is the price of a tune-up?"
    - "Which is the price of a new seat?"
    - "What can I do to take care of my bike?"

chatbot:
  is_starter: False
  fallback: I'm sorry it's a little loud in my shop, can you say that again?
  output:
    - opening_and_closing:
        type: str
        description: the opening and closing time of the shop
    - tire:
        type: money
        description: the price of a new tire
    - tune_up:
        type: money
        description: the price of a tune-up
    - seat_price:
        type: money
        description: the price of a new seat
    - care_bike:
        type: str
        description: actions to take care of the bike

conversation:
  number: 5
  interaction_style:
    - default
```
"""

    assert validate_answer_yaml_status("profile", answer_text) == "valid"


def test_profile_validation_accepts_blockquoted_fenced_yaml_blocks():
    answer_text = """> Sure, here's a profile you can use.
>
> ```yaml
> test_name: qa
>
> llm:
>   temperature: 0.7
>   model: gpt-4o-mini
>
> user:
>   language: English
>   role: you have to act as a user talking to a virtual assistant of a bike shop
>   context:
>     - You are interested in asking the items below.
>     - Just stick to asking opening times, prices of tire, price of tune-up, price of seat, and actions to the care of bike. Do not ask anything else.
>   goals:
>     - "opening and closing time of the bike shop"
>     - "Which is the price of a new tire?"
>     - "Which is the price of a tune-up?"
>     - "Which is the price of a new seat?"
>     - "What can I do to take care of my bike?"
>
> chatbot:
>   is_starter: False
>   fallback: I'm sorry it's a little loud in my shop, can you say that again?
>   output:
>     - opening_and_closing:
>         type: str
>         description: the opening and closing time of the shop
>     - tire:
>         type: money
>         description: the price of a new tire
>     - tune_up:
>         type: money
>         description: the price of a tune-up
>     - seat_price:
>         type: money
>         description: the price of a new seat
>     - care_bike:
>         type: str
>         description: actions to take care of the bike
>
> conversation:
>   number: 5
>   interaction_style:
>     - default
> ```
"""

    assert validate_answer_yaml_status("profile", answer_text) == "valid"
