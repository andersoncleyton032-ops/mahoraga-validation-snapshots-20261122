import numpy as np

from agent.neural_core import NeuralError


class TrainingError(Exception):
    pass


def _dataset(inputs, targets, name):
    try:
        x = np.asarray(inputs, dtype=np.float32)
        y = np.asarray(targets, dtype=np.float32)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TrainingError(f"{name}: dados inválidos.") from exc

    if x.ndim != 2 or y.ndim != 2:
        raise TrainingError(f"{name}: entradas e alvos devem ser matrizes 2D.")
    if x.shape[0] == 0 or y.shape[0] == 0:
        raise TrainingError(f"{name}: conjunto vazio.")
    if x.shape[0] != y.shape[0]:
        raise TrainingError(f"{name}: quantidades de exemplos diferentes.")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise TrainingError(f"{name}: valores não finitos.")
    return x, y


def _snapshot_training_state(network, optimizer):
    parameters = network.parameters()
    weights = [p.data.copy() for p in parameters]
    optimizer_state = None

    if hasattr(optimizer, "state") and hasattr(optimizer, "step_count"):
        if not isinstance(optimizer.state, dict):
            raise TrainingError("Estado do otimizador incompatível.")

        moments = []
        for parameter in parameters:
            state = optimizer.state.get(id(parameter))
            if state is None:
                m = np.zeros_like(parameter.data)
                v = np.zeros_like(parameter.data)
            else:
                m = np.asarray(state["m"]).copy()
                v = np.asarray(state["v"]).copy()

            if m.shape != parameter.data.shape or v.shape != parameter.data.shape:
                raise TrainingError("Formato inválido no estado do Adam.")
            if not np.all(np.isfinite(m)) or not np.all(np.isfinite(v)):
                raise TrainingError("Estado do Adam inválido.")
            moments.append((m, v))

        optimizer_state = (int(optimizer.step_count), moments)

    return weights, optimizer_state


def _restore_training_state(network, optimizer, snapshot):
    weights, optimizer_state = snapshot
    parameters = network.parameters()

    if len(weights) != len(parameters):
        raise TrainingError("Quantidade de parâmetros incompatível.")

    checked_weights = []
    for parameter, saved in zip(parameters, weights):
        value = np.asarray(saved, dtype=parameter.data.dtype)
        if value.shape != parameter.data.shape or not np.all(np.isfinite(value)):
            raise TrainingError("Checkpoint interno de pesos inválido.")
        checked_weights.append(value.copy())

    checked_moments = None
    if optimizer_state is not None:
        if not hasattr(optimizer, "state") or not hasattr(optimizer, "step_count"):
            raise TrainingError("Otimizador incompatível com a restauração.")

        step_count, moments = optimizer_state
        if len(moments) != len(parameters) or step_count < 0:
            raise TrainingError("Checkpoint interno do Adam inválido.")

        checked_moments = {}
        for parameter, pair in zip(parameters, moments):
            m = np.asarray(pair[0], dtype=parameter.data.dtype)
            v = np.asarray(pair[1], dtype=parameter.data.dtype)
            if m.shape != parameter.data.shape or v.shape != parameter.data.shape:
                raise TrainingError("Dimensões do Adam incompatíveis.")
            if not np.all(np.isfinite(m)) or not np.all(np.isfinite(v)):
                raise TrainingError("Estado salvo do Adam inválido.")
            checked_moments[id(parameter)] = {"m": m.copy(), "v": v.copy()}

    for parameter, value in zip(parameters, checked_weights):
        parameter.data[...] = value

    if checked_moments is not None:
        optimizer.state = checked_moments
        optimizer.step_count = int(optimizer_state[0])

    if hasattr(network, "ready"):
        network.ready = False


def _validate_loss(loss_value, gradient=None):
    if not np.isfinite(loss_value):
        raise NeuralError("Perda inválida ou não finita.")
    if gradient is not None and not np.all(np.isfinite(gradient)):
        raise NeuralError("Gradiente inválido ou não finito.")


class Trainer:
    def __init__(
        self, network, optimizer, loss,
        batch_size=16, shuffle=True, seed=42, clip=5.0,
    ):
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size deve ser um inteiro positivo.")
        if not isinstance(shuffle, bool):
            raise ValueError("shuffle deve ser booleano.")
        if not np.isfinite(clip) or clip <= 0:
            raise ValueError("clip deve ser positivo e finito.")
        if not callable(getattr(network, "train_step", None)):
            raise TypeError("Rede incompatível.")
        if not callable(getattr(network, "forward", None)) or not callable(getattr(network, "parameters", None)):
            raise TypeError("Interface da rede incompleta.")
        if not callable(getattr(loss, "forward_backward", None)):
            raise TypeError("Função de perda incompatível.")
        if not callable(getattr(optimizer, "step", None)):
            raise TypeError("Otimizador incompatível.")

        self.network = network
        self.optimizer = optimizer
        self.loss = loss
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.clip = float(clip)
        try:
            self.rng = np.random.default_rng(seed)
        except (TypeError, ValueError) as exc:
            raise ValueError("seed inválida.") from exc
        self.history = []

    def evaluate(self, inputs, targets):
        x, y = _dataset(inputs, targets, "Validação")
        total_loss = 0.0
        total_samples = 0

        for start in range(0, len(x), self.batch_size):
            end = min(start + self.batch_size, len(x))
            prediction = self.network.forward(x[start:end])
            if prediction.shape != y[start:end].shape:
                raise TrainingError("Formato de saída incompatível com os alvos.")

            loss_value, gradient = self.loss.forward_backward(prediction, y[start:end])
            _validate_loss(loss_value, gradient)

            samples = end - start
            total_loss += float(loss_value) * samples
            total_samples += samples

        return total_loss / total_samples

    def fit(
        self, inputs, targets, epochs=100,
        validation_data=None, patience=None, min_delta=0.0,
    ):
        x, y = _dataset(inputs, targets, "Treinamento")

        if isinstance(epochs, bool) or not isinstance(epochs, int) or epochs < 1:
            raise ValueError("epochs deve ser um inteiro positivo.")
        if patience is not None:
            if isinstance(patience, bool) or not isinstance(patience, int) or patience < 1:
                raise ValueError("patience deve ser None ou inteiro positivo.")
        if not np.isfinite(min_delta) or min_delta < 0:
            raise ValueError("min_delta inválido.")

        validation = None
        if validation_data is not None:
            if not isinstance(validation_data, (tuple, list)) or len(validation_data) != 2:
                raise TrainingError("validation_data deve conter entradas e alvos.")
            validation = _dataset(validation_data[0], validation_data[1], "Validação")
            if validation[0].shape[1] != x.shape[1]:
                raise TrainingError("Dimensão das entradas de validação incompatível.")

        history_start = len(self.history)
        best_validation = float("inf")
        patience_best = float("inf")
        best_state = None
        best_epoch = None
        epochs_without_improvement = 0
        stopped_early = False

        for epoch in range(epochs):
            indices = self.rng.permutation(len(x)) if self.shuffle else np.arange(len(x))
            epoch_loss = 0.0
            epoch_gradient = 0.0
            total_samples = 0

            for start in range(0, len(x), self.batch_size):
                batch_indices = indices[start:start + self.batch_size]
                result = self.network.train_step(
                    x[batch_indices], y[batch_indices],
                    self.loss, self.optimizer, clip=self.clip,
                )

                samples = len(batch_indices)
                _validate_loss(result["loss"])
                if not np.isfinite(result["gradient_norm"]):
                    raise NeuralError("Norma do gradiente inválida.")

                epoch_loss += float(result["loss"]) * samples
                epoch_gradient += float(result["gradient_norm"]) * samples
                total_samples += samples

            record = {
                "epoch": epoch + 1,
                "loss": epoch_loss / total_samples,
                "gradient_norm": epoch_gradient / total_samples,
                "samples": total_samples,
            }

            if validation is not None:
                validation_loss = self.evaluate(*validation)
                record["validation_loss"] = validation_loss

                if validation_loss < best_validation:
                    best_validation = validation_loss
                    best_state = _snapshot_training_state(self.network, self.optimizer)
                    best_epoch = epoch + 1

                if validation_loss < patience_best - min_delta:
                    patience_best = validation_loss
                    epochs_without_improvement = 0
                else:
                    epochs_without_improvement += 1

            self.history.append(record)

            if patience is not None and validation is not None and epochs_without_improvement >= patience:
                stopped_early = True
                break

        restored_best_state = False
        if validation is not None and best_state is not None:
            _restore_training_state(self.network, self.optimizer, best_state)
            restored_best_state = True

        run_history = self.history[history_start:]
        return {
            "history": list(run_history),
            "epochs_completed": len(run_history),
            "stopped_early": stopped_early,
            "best_validation_loss": best_validation if validation is not None else None,
            "best_epoch": best_epoch,
            "restored_best_state": restored_best_state,
        }
