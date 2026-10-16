{# Hand-rolled generic tests.

   dbt_utils would give me these for free, but it needs `dbt deps` and network
   access at build time. Writing the two I actually use keeps this project
   runnable offline, which matters for a portfolio: a reviewer who cannot build
   it will assume it does not build. #}

{% test not_negative(model, column_name) %}

    select {{ column_name }}
    from {{ model }}
    where {{ column_name }} < 0

{% endtest %}


{% test dbt_utils_accepted_range(model, column_name, min_value, max_value) %}

    select {{ column_name }}
    from {{ model }}
    where {{ column_name }} is not null
      and ({{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }})

{% endtest %}
