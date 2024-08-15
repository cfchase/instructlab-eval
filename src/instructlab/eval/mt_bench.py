# SPDX-License-Identifier: Apache-2.0

"""
Multi-Turn Benchmark
https://klu.ai/glossary/mt-bench-eval
https://arxiv.org/html/2306.05685
"""

# Standard
import multiprocessing
import os

# First Party
from instructlab.eval import (
    mt_bench_answers,
    mt_bench_branch_generator,
    mt_bench_judgment,
)
from instructlab.eval.exceptions import InvalidMaxWorkersError

# Local
from .evaluator import Evaluator
from .logger_config import setup_logger

logger = setup_logger(__name__)


class AbstractMTBenchEvaluator(Evaluator):
    """
    Abstract class of an MTBenchEvaluator for Multi-turn Benchmark (MT-Bench)

    Attributes
        model_name                  Name of the model to evaluate
        judge_model_name            Name of the judge model
        output_dir                  The directory to use for evaluation output
        max_workers                 Max parallel workers to run the evaluation with (int or "auto")
        serving_gpus                Number of gpus allocated for serving.  Used to tune with max_workers=auto.
        merge_system_user_message   Boolean indicating whether to merge system and user messages (required for Mistral based judges)
    """

    def __init__(
        self,
        model_name: str,
        judge_model_name: str,
        output_dir: str = "eval_output",
        max_workers: int | str = "auto",
        serving_gpus: int | None = None,
        merge_system_user_message: bool = False,
    ) -> None:
        self.model_name = model_name
        self.judge_model_name = judge_model_name
        self.output_dir = output_dir
        self.serving_gpus = serving_gpus
        self.merge_system_user_message = merge_system_user_message

        if max_workers == "auto":
            try:
                # Not available on all platforms
                usable_cpu_count = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
            except AttributeError:
                usable_cpu_count = multiprocessing.cpu_count()
            if serving_gpus is not None:
                # Tune max_workers based on hardware configuration: min(#GPUs being used * 10, #CPU cores)
                # Please see https://github.com/instructlab/instructlab/issues/2050 for detailed explanation
                self.max_workers = min(max(serving_gpus, 1) * 10, usable_cpu_count)
                logger.debug("Auto tuning max_workers to %s", self.max_workers)
            else:
                # Don't be too aggressive when serving_gpus isn't specified. Use half the cpu count.
                self.max_workers = usable_cpu_count // 2
                logger.debug(
                    "max_workers set to auto but serving_gpus is not specified. Defaulting to (cpu count / 2): %s",
                    self.max_workers,
                )
        else:
            if isinstance(max_workers, int) and max_workers > 0:
                logger.debug("max_workers specified as: %s", max_workers)
                self.max_workers = max_workers
            else:
                raise InvalidMaxWorkersError(max_workers)


class MTBenchEvaluator(AbstractMTBenchEvaluator):
    """
    Evaluator for Multi-turn Benchmark (MT-Bench)

    Attributes
        model_name                  Name of the model to evaluate
        judge_model_name            Name of the judge model
        output_dir                  The directory to use for evaluation output
        max_workers                 Max parallel workers to run the evaluation with (int or "auto")
        serving_gpus                Number of gpus allocated for serving.  Used to tune with max_workers=auto.
        merge_system_user_message   Boolean indicating whether to merge system and user messages (required for Mistral based judges)
    """

    name = "mt_bench"

    def gen_answers(self, server_url) -> None:
        """
        Asks questions to model

        Attributes
            server_url      Model server endpoint (Ex: http://localhost:8000/v1) for the model being evaluated
        """
        logger.debug(locals())
        mt_bench_answers.generate_answers(
            self.model_name,
            server_url,
            output_dir=self.output_dir,
            max_workers=self.max_workers,
        )

    def judge_answers(self, server_url) -> tuple:
        """
        Runs MT-Bench judgment

        Attributes
            server_url      Model server endpoint (Ex: http://localhost:8000/v1) for the judge model

        Returns:
            overall_score   MT-Bench score for the overall model evaluation
            qa_pairs        Question and answer pairs (with scores) from the evaluation
            turn_scores     A list of indexed turn scores
        """
        logger.debug(locals())
        return mt_bench_judgment.generate_judgment(
            self.model_name,
            self.judge_model_name,
            server_url,
            max_workers=self.max_workers,
            output_dir=self.output_dir,
            merge_system_user_message=self.merge_system_user_message,
        )


class MTBenchBranchEvaluator(AbstractMTBenchEvaluator):
    """
    Evaluator for comparing taxonomy branches with MT-Bench-Branch Benchmark

    Attributes
        model_name                  Name of the model to evaluate
        judge_model_name            Name of the judge model
        taxonomy_git_repo_path      Taxonomy git repo path
        branch                      Branch of taxonomy repo to eval QNAs against model
        output_dir                  The directory to use for evaluation output
        max_workers                 Max parallel workers to run the evaluation with (int or "auto")
        serving_gpus                Number of gpus allocated for serving.  Used to tune with max_workers=auto.
        merge_system_user_message   Boolean indicating whether to merge system and user messages (required for Mistral based judges)
    """

    name = "mt_bench_branch"

    def __init__(
        self,
        model_name: str,
        judge_model_name: str,
        taxonomy_git_repo_path: str,
        branch: str,
        output_dir: str = "eval_output",
        max_workers: int | str = "auto",
        serving_gpus: int | None = None,
        merge_system_user_message: bool = False,
    ) -> None:
        super().__init__(
            model_name,
            judge_model_name,
            output_dir,
            max_workers,
            serving_gpus,
            merge_system_user_message,
        )
        self.taxonomy_git_repo_path = taxonomy_git_repo_path
        self.branch = branch

    def gen_answers(self, server_url) -> None:
        """
        Asks questions to model

        Attributes
            server_url  Model server endpoint (Ex: http://localhost:8000/v1) for the model being evaluated
        """
        logger.debug(locals())
        mt_bench_branch_generator.generate(
            self.judge_model_name,
            self.branch,
            self.taxonomy_git_repo_path,
            self.output_dir,
        )
        mt_bench_answers.generate_answers(
            self.model_name,
            server_url,
            branch=self.branch,
            output_dir=self.output_dir,
            data_dir=self.output_dir,
            max_workers=self.max_workers,
            bench_name="mt_bench_branch",
        )

    def judge_answers(self, server_url) -> tuple:
        """
        Runs MT-Bench-Branch judgment.  Judgments can be compared across runs with consistent question_id -> qna file name.

        Attributes
            server_url      Model server endpoint (Ex: http://localhost:8000/v1) for the judge model

        Returns:
            qa_pairs        Question and answer pairs (with scores) from the evaluation
        """
        logger.debug(locals())
        _, qa_pairs, _, error_rate = mt_bench_judgment.generate_judgment(
            self.model_name,
            self.judge_model_name,
            server_url,
            branch=self.branch,
            max_workers=self.max_workers,
            output_dir=self.output_dir,
            data_dir=self.output_dir,
            bench_name="mt_bench_branch",
            merge_system_user_message=self.merge_system_user_message,
        )
        return qa_pairs, error_rate
