 out="myscript/results/plot_timing/gpt-6.2-sol-2-$(date +%Y%m%d-%H%M%S)"

  .venv/bin/python -m minisweagent.run.benchmarks.swebench \
    --subset lite \
    --split test \
    --filter '^astropy__astropy-(12907|14365)$' \
    --workers 1 \
    --model 'openai/gpt-6.1-sol' \
    -o "$out" \
    -c swebench.yaml \
    -c agent.step_limit=30 \
    -c agent.cost_limit=3 \
    -c 'environment.run_args=["--rm","--platform=linux/amd64"]' \
    -c environment.pull_timeout=600 \
  && .venv/bin/python myscript/plot_timing.py "$out" -o "$out/timing-report.html" \
  && open "$out/timing-report.html"


 out="myscript/results/plot_timing/deepseek-flash-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python -m minisweagent.run.benchmarks.swebench \
  --subset lite \
  --split test \
  --slice '0:10' \
  --workers 1 \
  --model 'deepseek/deepseek-flash' \
  --k 0 \
  -o "$out" \
  -c swebench.yaml \
  -c agent.step_limit=30 \
  -c agent.cost_limit=3 \
  -c 'environment.run_args=["--rm","--platform=linux/amd64"]' \
  -c environment.pull_timeout=600 \
&& .venv/bin/python myscript/plot_timing.py "$out" \
  -o "$out/timing-report.html" \
&& open "$out/timing-report.html"