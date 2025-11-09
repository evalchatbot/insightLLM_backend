-- Drop and recreate the record_usage function with better increment logic
CREATE OR REPLACE FUNCTION public.record_usage(
    p_user_id uuid,
    p_input_tokens integer DEFAULT 0,
    p_output_tokens integer DEFAULT 0,
    p_pages integer DEFAULT 0
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    current_period date;
    is_pro boolean;
    usage_record record;
    free_input_limit integer := 250000;   -- 250K tokens
    free_output_limit integer := 500000;  -- 500K tokens
    free_pages_limit integer := 50;       -- 50 pages
    pro_input_limit integer := 1000000;   -- 1M tokens
    pro_output_limit integer := 3000000;  -- 3M tokens
    pro_pages_limit integer := 1000;      -- 1K pages
BEGIN
    -- Get current period
    current_period := date_trunc('month', CURRENT_DATE)::date;
    
    -- Check if user has an active pro key
    SELECT EXISTS (
        SELECT 1 FROM keys 
        WHERE used_by = p_user_id 
        AND is_used = true 
        AND expiry_date > CURRENT_TIMESTAMP
    ) INTO is_pro;
    
    IF is_pro THEN
        -- Ensure pro usage record exists and update it
        INSERT INTO public.usage_pro (
            user_id,
            period_start,
            tokens_input_used,
            tokens_output_used,
            pages_used,
            last_used,
            created_at,
            updated_at
        )
        VALUES (
            p_user_id,
            current_period,
            GREATEST(p_input_tokens, 0),
            GREATEST(p_output_tokens, 0),
            GREATEST(p_pages, 0),
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (user_id, period_start) 
        DO UPDATE SET
            tokens_input_used = usage_pro.tokens_input_used + GREATEST(p_input_tokens, 0),
            tokens_output_used = usage_pro.tokens_output_used + GREATEST(p_output_tokens, 0),
            pages_used = usage_pro.pages_used + GREATEST(p_pages, 0),
            last_used = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
        INTO usage_record;

        -- Check pro limits
        IF (
            usage_record.tokens_input_used > pro_input_limit OR
            usage_record.tokens_output_used > pro_output_limit OR
            usage_record.pages_used > pro_pages_limit
        ) THEN
            RETURN jsonb_build_object(
                'success', false,
                'message', 'Pro plan usage limit exceeded',
                'is_pro', true,
                'usage', jsonb_build_object(
                    'tokens_input_used', usage_record.tokens_input_used,
                    'tokens_output_used', usage_record.tokens_output_used,
                    'pages_used', usage_record.pages_used,
                    'period_start', usage_record.period_start,
                    'last_used', usage_record.last_used
                )
            );
        END IF;
    ELSE
        -- Ensure free usage record exists and update it
        INSERT INTO public.usage_free (
            user_id,
            period_start,
            tokens_input_used,
            tokens_output_used,
            pages_used,
            last_used,
            created_at,
            updated_at
        )
        VALUES (
            p_user_id,
            current_period,
            GREATEST(p_input_tokens, 0),
            GREATEST(p_output_tokens, 0),
            GREATEST(p_pages, 0),
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (user_id, period_start) 
        DO UPDATE SET
            tokens_input_used = usage_free.tokens_input_used + GREATEST(p_input_tokens, 0),
            tokens_output_used = usage_free.tokens_output_used + GREATEST(p_output_tokens, 0),
            pages_used = usage_free.pages_used + GREATEST(p_pages, 0),
            last_used = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        RETURNING *
        INTO usage_record;

        -- Check free limits
        IF (
            usage_record.tokens_input_used > free_input_limit OR
            usage_record.tokens_output_used > free_output_limit OR
            usage_record.pages_used > free_pages_limit
        ) THEN
            RETURN jsonb_build_object(
                'success', false,
                'message', 'Free plan usage limit exceeded',
                'is_pro', false,
                'usage', jsonb_build_object(
                    'tokens_input_used', usage_record.tokens_input_used,
                    'tokens_output_used', usage_record.tokens_output_used,
                    'pages_used', usage_record.pages_used,
                    'period_start', usage_record.period_start,
                    'last_used', usage_record.last_used
                )
            );
        END IF;
    END IF;

    -- Return success with usage info
    RETURN jsonb_build_object(
        'success', true,
        'message', 'Usage recorded successfully',
        'is_pro', is_pro,
        'usage', jsonb_build_object(
            'tokens_input_used', usage_record.tokens_input_used,
            'tokens_output_used', usage_record.tokens_output_used,
            'pages_used', usage_record.pages_used,
            'period_start', usage_record.period_start,
            'last_used', usage_record.last_used
        )
    );
END;
$$;

-- Grant execute permission to service role
GRANT EXECUTE ON FUNCTION public.record_usage(uuid, integer, integer, integer) TO service_role;